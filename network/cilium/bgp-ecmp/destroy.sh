#!/bin/bash


clab destroy -t topo.yaml
kind delete cluster -n cilium-lb
