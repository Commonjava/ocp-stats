
import openshift
import sys
from time import sleep

print('Python version: {}'.format(sys.version))
print('OpenShift client version: {}'.format(openshift.get_client_version()))
print('OpenShift server version: {}'.format(openshift.get_server_version()))

while True:
    nodes = openshift.selector('nodes').objects()
    print(nodes)

    print('Sleeping 30 seconds')
    sleep(30)