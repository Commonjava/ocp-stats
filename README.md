# OCP Stats

This is a microservice aimed at answering the question: 

	Given a pod with certain CPU and memory requirement (or a cluster of such pods of a given size), how many instances could I deploy in my current Openshift cluster?

To answer this question, the code accumulates node capacities and load factors (by querying active pods on each node), then condenses these statistics into various measurements of the remaining capacity (based on requested resources, or minimums, and not on limits, which are maximums). 

Once the per-node statistics are compiled, these stats are compared against a list of runtime profiles that each correspond to a metric name. The result is a mapping of metric names to the number of copies that could be deployed (all other considerations being equal). 

Finally, the result of our metric comparisons are published to a time-series database (currently hard-coded to talk to the plaintext port on a GraphiteDB/Carbon service).

## Metric Profiles (`$METRIC_MAP`)

To publish a set of capacities, we need runtime profiles for each metric we want to watch. These are stored in a YAML file that looks something like this:

```
---
metrics:
  - metric: ocp.indy.node.capacity
    cpu: 24
    memory: 24Gi
  - metric: ocp.cassandra.node.capacity
    cpu: 4
    memory: 8Gi
  - metric: ocp.cassandra.cluster.capacity
    cpu: 4
    memory: 8Gi
    pods: 5
  - metric: ocp.jenkins.builder.capacity
    cpu: 4
    memory: 12Gi
```

In our running container, we tell the service to read the metric map using an environment variable called `METRIC_MAP`.

## Other Environment Variables

Beyond the `METRIC_MAP` environment variable, mentioned above, OCP Stats uses a few more to control its access to the Openshift cluster and the Carbon service:

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

