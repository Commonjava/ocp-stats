# OCP Stats

This is a microservice aimed at answering the question: 

    Given a pod with certain CPU and memory requirement (or a cluster of such pods of a given size), how many instances could I deploy in my current Openshift cluster?

To answer this question, the code accumulates node capacities and load factors (by querying active pods on each node), then condenses these statistics into various measurements of the remaining capacity (based on requested resources, or minimums, and not on limits, which are maximums). 

Once the per-node statistics are compiled, these stats are compared against a list of runtime profiles that each correspond to a metric name. The result is a mapping of metric names to the number of copies that could be deployed (all other considerations being equal). 

Finally, the result of our metric comparisons are published to a time-series database (currently hard-coded to talk to the plaintext port on a GraphiteDB/Carbon service).

## Carbon / GraphiteDB Metrics (`$METRIC_MAP`)

In our running container, we tell the service to read the metric map using an environment variable called `METRIC_MAP`. The format of this YAML file is detailed below.

By comparing these hypothetical profiles or deploymentconfig references to the cluster load and maximum capacity, the application will render a result similar to:

```
ocp.indy.node.capacity 2 1596645322
```

### Hypothetical Metric Profiles

At times, we may wish to know how many of a given type of deployment we might have space for inside the cluster *without first deploying anything new*. To handle this, the application contains a section of metric profiles named `hypothetical`. These specify optional cpu, memory, and pod count criteria, which are used to calculate the cluster's capacity to host deployments that match those footprints. 

**NOTE: All of the profile parameters are optional here. If none of them are specified, the metric will be skipped.**

To publish a set of capacities based on hypothetical deployment sizes, we need  profiles for each metric we want to watch. These are stored in a YAML map named `hypothetical`, that looks something like this:

```yaml
---
hypothetical:
  - name: ocp.indy.node.capacity
    cpu: 24
    memory: 24Gi
  - name: ocp.cassandra.node.capacity
    cpu: 4
    memory: 8Gi
  - name: ocp.cassandra.cluster.capacity
    cpu: 4
    name: 8Gi
    pods: 5
  - name: ocp.jenkins.builder.capacity
    cpu: 4
    memory: 12Gi
```

### DeploymentConfig Metric Profiles

The other way to track capacity is by comparing available capacity to the sizes of existing deployments we're trying to scale and maintain. In this case, the specific questions revolve around whether we're able to redeploy or increase the scale of the deployment as a production support function. The main advantage to tracking existing deployments, rather than creating hypothetical profiles that match the same deployment sizes, is that we won't introduce a new maintenance point. By tracking the deployments themselves, we can adjust our metrics automatically when we adjust the actual deployments, and avoid the manual update of our metrics.

To publish a set of capacities based on existing deployments, we need a list of deployments (with namespaces). These are stored in a YAML map named `existing`, like this:

```yaml
---
existing:
  - name: ocp.indy.node.capacity
    namespace: my-project
    deployment: my-indy
  - name: ocp.cassandra.node.capacity
    namespace: my-project
    deployment: my-cassie
  - name: ocp.cassandra.cluster.capacity
    namespace: my-project
    deployment: my-cassie-cluster
    include-replica-count: true
```

## Other Environment Variables

Beyond the `METRIC_MAP` environment variable, mentioned above, OCP Stats uses a few more to control its access to the Openshift cluster and the Carbon service. Here is the full list of variables:

* `METRIC_MAP`: Path to the YAML file containing the metrics we wish to produce, and the criteria for generating them from the node statistics.
* `SVC_ACCT_DIR`: Directory where the Openshift `serviceaccount` secrets are located, which will contain the crucial `token` file.
	* *This variable will default to `/var/run/secrets/kubernetes.io/serviceaccount` if unspecified.*
* `API_URL`: URL to the Openshift API (without any path elements)
	* *This variable will default to `https://openshift.default.svc.cluster.local:443` if unspecified, which should allow a pod to query its own environment.*
* `CARBON_HOST`: The hostname of the Carbon service
* `CARBON_PORT`: The port for the plaintext endpoint on the Carbon service
	* *This variable will default to `2003` if unspecified.*
* `SLEEP_MINUTES`: The number of minutes between metric publishing runs.
	* Since it's fairly expensive to calculate these capacities, we will only run in minute increments. It's probably wise to set this to >10 mins.
	* *This variable will default to `10` if unspecified.*

