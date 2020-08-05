#!/usr/bin/env python

import os
import socket
from time import time, sleep
from datetime import datetime as dt
from math import floor
from sys import stdout
from ruamel.yaml import YAML
from kubernetes import client
from openshift.dynamic import DynamicClient

SVC_ACCT_DIR = (
    os.environ.get("SVC_ACCT_DIR") or "/var/run/secrets/kubernetes.io/serviceaccount"
)
API_URL = os.environ.get("API_URL") or "https://openshift.default.svc.cluster.local:443"
TOKEN_PATH = os.path.join(SVC_ACCT_DIR, "token")
CARBON_HOST = os.environ.get("CARBON_HOST")
CARBON_PORT = os.environ.get("CARBON_PORT") or 2003
METRIC_MAP_PATH = os.environ.get("METRIC_MAP") or "/var/run/ocp-stats/metric-map.yaml"
SLEEP_MINUTES = int(os.environ.get("SLEEP_MINUTES") or 10)

yaml = YAML(typ="safe")
yaml.indent(mapping=2, sequence=2, offset=2)
yaml.default_flow_style = False


def compile_metrics(node_map):
    """
    Compile the current capacities of various metric profiles against the available capacity we've found in the
    nodes.

    :param node_map: The mapping of per-node available capacity (among other things)
    :return: The mapping of metric-name to metric-value (where value is the number of a particular metric profile that
             we could deploy into the cluster)
    """

    if not os.path.exists(METRIC_MAP_PATH):
        raise Exception(f"Cannot read metric-map YAML from {METRIC_MAP_PATH}")

    with open(METRIC_MAP_PATH) as f:
        metric_map = yaml.load(f)

    metric_criteria = metric_map.get("metrics") or []

    metric_values = dict()
    for metric in metric_criteria:
        # print(f"Looking for capacity of metric: {metric['metric']}")
        metric_capacity = 0
        for node in node_map.values():
            # print(f"Examining available capacity in node: {node['name']}")
            pods = node["available"]["pods"]
            cpu = node["available"]["cpu"]
            mem = node["available"]["memory"]

            node_capacity = 0

            m_cpu = parse_cpu(metric.get("cpu"))
            # print(f"Comparing required CPU: {m_cpu} to node available CPU: {cpu}")
            if m_cpu is not None and cpu > m_cpu:
                m_count = floor(cpu / m_cpu)
                # print(f"Node has {m_count} capacity in terms of CPU")
                node_capacity = (
                    m_count if node_capacity < 1 else min(m_count, node_capacity)
                )

            m_mem = parse_mem(metric.get("memory"))
            # print(f"Comparing required Memory: {m_mem} to node available Memory: {mem}")
            if m_mem is not None and mem > m_mem:
                m_count = floor(mem / m_mem)
                # print(f"Node has {m_count} capacity in terms of Memory")
                node_capacity = (
                    m_count if node_capacity < 1 else min(m_count, node_capacity)
                )

            node_capacity = 1 if node_capacity < 1 else min(node_capacity, pods)
            # print(f"Node has capacity: {node_capacity}")

            metric_capacity += node_capacity

        m_pods = metric.get("pods")
        # print(f"Comparing required pods: {m_pods} to total available pods: {metric_capacity}")
        if m_pods is not None and metric_capacity > m_pods:
            metric_capacity = floor(metric_capacity / m_pods)

        # print(f"{metric['metric']} = {metric_capacity}")
        metric_values[metric["metric"]] = metric_capacity

    return metric_values


def send_metrics(metrics):
    """
    Send the metrics returned from compile_metrics to a Carbon service (the metric-ingress for GraphiteDB), using
    a generated timestamp that is consistent for all metrics.

    :param metrics: Dictionary containing metric-name to metric-value
    :return: None
    """

    conn_info = (CARBON_HOST, CARBON_PORT)
    now = int(time())
    try:
        with socket.socket() as sock:
            print("Connecting to: %s:%d" % conn_info)
            sock.connect(conn_info)
            for (metric, value) in metrics.items():
                line = f"{metric} {value} {now}\n"
                print("Sending:\n%s" % line)
                sock.send(bytes(line, "utf-8"))
    except socket.error:
        raise SystemExit("Couldn't connect to %s:%d" % conn_info)


def parse_cpu(raw_cpu):
    """
    Parse an Openshift-style CPU resource request/limit notation into a whole/fractional (float) CPU number.

    :param raw_cpu: The raw CPU notation (may be int, float, or an Openshift-style string)
    :return: The floating point number of CPUs represented in the notation
    """

    if raw_cpu is None:
        return None

    if isinstance(raw_cpu, int) or isinstance(raw_cpu, float):
        return raw_cpu

    cpu = str(raw_cpu)
    if cpu.endswith("m"):
        return int(cpu[:-1]) / 1000

    return int(cpu)


def parse_mem(raw_mem):
    """
    Parse an Openshift-style memory resource request/limit notation into an integer memory number (of bytes).

    :param raw_mem: The raw memory notation (may be int or an Openshift-style string)
    :return: The integer number of memory (bytes) represented in the notation
    """

    if raw_mem is None:
        return None

    if isinstance(raw_mem, int):
        return raw_mem

    mem = str(raw_mem)
    if "'" in mem:
        mem = mem[1:-1]

    if mem.endswith("Gi"):
        return int(mem[:-2]) * 1024 * 1024 * 1024
    elif mem.endswith("G"):
        return int(mem[:-1]) * 1024 * 1024 * 1024
    elif mem.endswith("Mi"):
        return int(mem[:-2]) * 1024 * 1024
    elif mem.endswith("M"):
        return int(mem[:-1]) * 1024 * 1024
    elif mem.endswith("Ki"):
        return int(mem[:-2]) * 1024
    elif mem.endswith("K"):
        return int(mem[:-1]) * 1024
    elif mem.endswith("m"):
        # TODO: I'm not sure if this notation is legal, or what Openshift does with it.
        return int(mem[:-1])

    return int(mem)


def init_node(node_name):
    """
    Initialize a dictionary for receiving information about a node's runtime statistics. This is intended to allow
    us to refactor the logic for accumulating node-to-pod information without risking a dictionary initialization
    problem.

    :param node_name: The name of the node to use
    :return: a new dict with placeholders corresponding to data that we will allocate about pods running on a node
    """

    return {
        "name": node_name,
        "pods": [],
        "cpuRequests": [],
        "cpuLimits": [],
        "memoryRequests": [],
        "memoryLimits": [],
    }


def process_pod(pod, node_info):
    """
    Extract relevant resource information about a pod running on a node, and add it to the stats for that node. Do NOT
    execute any math for the node resources; instead, simply accumulate the pod stats into arrays in the node info.

    :param pod: The pod information, from Openshift
    :param node_info: The dict containing accumulated pod-to-node stats for the node
    :return: None (the input node_info parameter is modified)
    """
    # print(f"Processing pod: {pod.metadata.name}")

    node_info["pods"].append(pod.metadata.name)

    for container in pod.spec.containers:
        if container.get("resources"):
            if container.resources.get("limits"):
                if container.resources.limits.get("cpu"):
                    node_info["cpuLimits"].append(
                        parse_cpu(container.resources.limits.cpu)
                    )
                if container.resources.limits.get("memory"):
                    node_info["memoryLimits"].append(
                        parse_mem(container.resources.limits.memory)
                    )
            if container.resources.get("requests"):
                if container.resources.requests.get("cpu"):
                    node_info["cpuRequests"].append(
                        parse_cpu(container.resources.requests.cpu)
                    )
                if container.resources.requests.get("memory"):
                    node_info["memoryRequests"].append(
                        parse_mem(container.resources.requests.memory)
                    )


def setup_oc():
    """
    Setup the Openshift client

    :return: The oc dynamic API client, used to bind resource clients for specific resource types
    """

    if not os.path.exists(TOKEN_PATH):
        raise Exception(f"Cannot read token from {TOKEN_PATH}")

    ocp_config = client.Configuration()
    ocp_config.host = API_URL
    ocp_config.verify_ssl = True

    ocp_config.ssl_ca_cert = os.path.join(SVC_ACCT_DIR, "ca.crt")
    ocp_config.assert_hostname = False

    with open(TOKEN_PATH) as f:
        ocp_config.api_key = {"authorization": f"Bearer {f.read()}"}

    k8s = client.ApiClient(ocp_config)
    return DynamicClient(k8s)


def compile_node_stats():
    """
    Retrieve and iterate through the nodes in an Openshift cluster, only processing nodes with a name prefix of 'cpt'.
    For each node, compile resource capacity stats into a master dict keyed by node name. Then, retrieve and iterate
    through all running pods on each node, accumulating resource consumption stats for each into the dict corresponding
    to that node (in the master dict of nodes).

    :return: A dict of node-level resource stats, keyed by node name. Each value is a dict of resource types and lists
    or capacities
    """

    oc = setup_oc()
    oc_pods = oc.resources.get(api_version="v1", kind="Pod")
    oc_nodes = oc.resources.get(api_version="v1", kind="Node")

    node_map = dict()

    # print("Processing nodes...")
    nodes = oc_nodes.get()
    for node in nodes.items:
        if "cpt" in node.metadata.name:
            print(f"Processing node: {node.metadata.name}")

            nodeInfo = node_map.get(node.metadata.name)
            if nodeInfo is None:
                nodeInfo = init_node(node.metadata.name)
                node_map[node.metadata.name] = nodeInfo

            if node.status.get("capacity"):
                if node.status.capacity.get("cpu"):
                    nodeInfo["cpuCapacity"] = parse_cpu(node.status.capacity.cpu)

                if node.status.capacity.get("memory"):
                    nodeInfo["memoryCapacity"] = parse_mem(node.status.capacity.memory)

                if node.status.capacity.get("pods"):
                    nodeInfo["podCapacity"] = int(node.status.capacity.pods)

            if node.status.get("allocatable"):
                if node.status.allocatable.get("cpu"):
                    nodeInfo["cpuAllocatable"] = parse_cpu(node.status.allocatable.cpu)

                if node.status.allocatable.get("memory"):
                    nodeInfo["memoryAllocatable"] = parse_mem(
                        node.status.allocatable.memory
                    )

                if node.status.allocatable.get("pods"):
                    nodeInfo["podAllocatable"] = int(node.status.allocatable.pods)

            # From oc client:
            # https://openshift.api.url:443/api/v1/pods?fieldSelector=spec.nodeName=<node-name>,status.phase!=Failed,status.phase!=Succeeded
            field_selector = f"spec.nodeName={node.metadata.name},status.phase!=Failed,status.phase!=Succeeded"
            node_pods = oc_pods.get(field_selector=field_selector)
            for pod in node_pods.items:
                process_pod(pod, nodeInfo)

    return node_map


def enrich_node_map(node_map):
    """
    Condense the accumulated statistics for each node in the supplied dict (values of the dict), calculating
    total request/limit cpu and memory, along with available cpu, memory, and pods.

    Condensed statistics will be used to match against the metric-mapping in order to arrive at a capacity
    per metric in the cluster.

    :param node_map: The master dictionary of node stats, keyed by node
    :return: None (condensed information is stored in the node_map parameter)
    """
    for nodeInfo in node_map.values():
        nodeInfo["allCpuRequests"] = sum(nodeInfo["cpuRequests"])
        nodeInfo["allMemoryRequests"] = sum(nodeInfo["memoryRequests"])
        nodeInfo["allCpuLimits"] = sum(nodeInfo["cpuLimits"])
        nodeInfo["allMemoryLimits"] = sum(nodeInfo["memoryLimits"])

        available = {
            "cpu": nodeInfo["cpuAllocatable"] - nodeInfo["allCpuRequests"],
            "memory": nodeInfo["memoryAllocatable"] - nodeInfo["allMemoryRequests"],
            "pods": nodeInfo["podAllocatable"] - len(nodeInfo["pods"]),
        }
        nodeInfo["available"] = available

        commitments = dict()
        nodeInfo["commitments"] = commitments

        commitments["cpuLimit"] = nodeInfo["allCpuLimits"] / nodeInfo["cpuAllocatable"]
        commitments["MemoryLimit"] = (
            nodeInfo["allMemoryLimits"] / nodeInfo["memoryAllocatable"]
        )
        commitments["cpuRequest"] = (
            nodeInfo["allCpuRequests"] / nodeInfo["cpuAllocatable"]
        )
        commitments["MemoryRequest"] = (
            nodeInfo["allMemoryRequests"] / nodeInfo["memoryAllocatable"]
        )

        commitments["pod"] = len(nodeInfo["pods"]) / nodeInfo["podAllocatable"]


def run():
    """
    Main control loop. Every N minutes, recalculate and publish cluster capacity metrics.
    :return: None
    """

    while True:
        print(f"Calculating cluster capacities at {dt.now()}")
        node_map = compile_node_stats()

        print("Condensing accumulated node stats")
        enrich_node_map(node_map)

        print("Calculating metric values")
        metric_values = compile_metrics(node_map)

        yaml.dump(metric_values, stdout)

        print("Publishing metrics")
        send_metrics(metric_values)

        if SLEEP_MINUTES < 1:
            break

        print(f"Sleeping {SLEEP_MINUTES} minutes")
        sleep(60 * SLEEP_MINUTES)


if __name__ == "__main__":
    run()
