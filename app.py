import openshift as oc
import sys

print('Python version: {}'.format(sys.version))
print('OpenShift client version: {}'.format(oc.get_client_version()))
print('OpenShift server version: {}'.format(oc.get_server_version()))

while True:
	#nop
	