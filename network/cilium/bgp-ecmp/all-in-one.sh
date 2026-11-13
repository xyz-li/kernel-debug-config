#!/bin/bash

# load dummy module
modprobe dummy

kind create cluster --config kind.yaml
clab deploy -t topo.yaml

docker exec clab-cilium-lb-router0 vtysh -c 'show bgp ipv4'
docker exec clab-cilium-lb-tor0 vtysh -c 'show bgp ipv4'
docker exec clab-cilium-lb-tor1 vtysh -c 'show bgp ipv4'

if [ ! -e cilium-image.tar ]; then
	echo "Downloading images"
	docker pull quay.io/cilium/cilium:v1.19.0
	docker pull quay.io/cilium/operator-generic:v1.19.0 
	docker pull quay.io/cilium/cilium-envoy:v1.35.9-1768828720-c6e4827ebca9c47af2a3a6540c563c30947bae29
	docker pull nginx:alpine
	docker save quay.io/cilium/cilium:v1.19.0 quay.io/cilium/operator-generic:v1.19.0 quay.io/cilium/cilium-envoy:v1.35.9-1768828720-c6e4827ebca9c47af2a3a6540c563c30947bae29 nginx:alpine -o cilium-image.tar
fi

echo "Loading images"
kind load image-archive -n cilium-lb ./cilium-image.tar

echo "Installing cilium"
cd cilium
helm install --wait --timeout 40s cilium -n kube-system .
cd -

kubectl create deploy nginx --image nginx:alpine
kubectl apply -f svc.yaml

echo "Check crds"
while true; do
	crds=$(kubectl get crd ciliumbgpclusterconfigs.cilium.io -oname)
	if [ "$crds" != "" ]; then
		kubectl apply -f bgp-config.yaml
		break
	else
		echo 'Waitting for cilium crds'
		sleep 1
	fi
done

#可在cilium-lb-control-plane 上使用curl 10.100.0.100. 
echo 'Run the subsquent command to check connectivity.'
echo "============"
echo 'docker exec -ti cilium-lb-control-plane curl 10.100.0.100'

