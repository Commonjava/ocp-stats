import openshift as oc
import sys
from time import sleep

print('Python version: {}'.format(sys.version))
print('OpenShift client version: {}'.format(oc.get_client_version()))
print('OpenShift server version: {}'.format(oc.get_server_version()))

while True:
    nodes = oc.selector('nodes').objects()
    print(nodes)

    print('Sleeping 30 seconds')
    sleep(30)