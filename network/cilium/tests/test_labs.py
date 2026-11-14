"""Exercise lab orchestration without creating clusters or modifying host networks."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('frr_checks', ROOT / 'common/check.py')
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)

MOCK = r'''
import json, os, sys
from pathlib import Path
tool = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['LAB_TEST_LOG'], 'a') as stream:
    stream.write(json.dumps(dict(tool=tool, args=args, cwd=os.getcwd(), kubeconfig=os.environ.get('KUBECONFIG'))) + '\n')
if os.environ.get('LAB_TEST_FAIL') == tool + ':' + (args[0] if args else ''):
    raise SystemExit(7)
if tool == 'uname': print(os.environ.get('LAB_TEST_OS', 'Linux'))
elif tool == 'df': print('Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/test 99999999 0 '+os.environ.get('LAB_TEST_FREE_KB','99999999')+' 0% /')
elif tool == 'id': print('0')
elif tool == 'sysctl' and args[0]=='-n':
    print('2097152' if os.environ.get('LAB_TEST_HIGH_INOTIFY') else '128')
elif tool == 'kind':
    if args[:2] == ['get','clusters']: print(os.environ.get('LAB_TEST_CLUSTERS',''))
    elif args[:2] == ['create','cluster']:
        Path(args[args.index('--kubeconfig')+1]).write_text('test kubeconfig\n')
elif tool == 'docker':
    if args[0] == 'info':
        print(os.environ.get('LAB_TEST_SECURITY','[]') if 'SecurityOptions' in args[-1] else 'linux')
    elif args[0] == 'context': print(os.environ.get('LAB_TEST_ENDPOINT','unix:///var/run/docker.sock'))
    elif args[:3] == ['image','save','--help']: print('--platform')
    elif args[:2] == ['image','inspect']: print('linux/arm64')
    elif args[0] == 'ps': print(os.environ.get('LAB_TEST_CONTAINERS',''))
    elif args[0] == 'exec' and args[2] == 'vtysh':
        command = args[-1]
        if 'summary json' in command:
            print(json.dumps({'ipv4Unicast':{'peers':{ip:{'state':'Established'} for ip in ['10.0.1.2','10.0.2.2','10.0.3.2','10.0.4.2']}}}))
        elif command.startswith('show ip route') and command.endswith('json'):
            prefix=command.split()[3]
            hops=['10.0.3.2','10.0.4.2'] if prefix=='10.100.0.100/32' else ['fe80::1']
            print(json.dumps({prefix:[dict(protocol='bgp',selected=True,installed=True,nexthops=[dict(ip=ip,fib=True) for ip in hops])]}))
elif tool == 'kubectl':
    assert args[:1] == ['--kubeconfig'] and args[2] == '--context', args
    args=args[4:]
    if args[:2] == ['get','crd'] and os.environ.get('LAB_TEST_MISSING_CRD'):
        raise SystemExit(1)
    if args[:2] == ['get','nodes'] and 'jsonpath=' in ' '.join(args):
        print('10.1.0.0/24\n10.1.1.0/24\n10.1.2.0/24\n10.1.3.0/24')
    elif args[:2] == ['get','pods']: print('10.1.1.2\n10.1.1.3')
'''


class LabTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='network lab ')
        self.root = Path(self.temporary.name).resolve()
        self.addCleanup(self.temporary.cleanup)
        shutil.copytree(ROOT / 'common', self.root / 'common', ignore=shutil.ignore_patterns('__pycache__', 'output'))
        shutil.copy2(ROOT / 'vm.sh', self.root / 'vm.sh')
        for lab in ('bgp', 'bgp-ecmp'):
            directory = self.root / lab
            directory.mkdir()
            (directory / 'cilium').mkdir()
            for name in ('all-in-one.sh','verify.sh','destroy.sh','kind.yaml','topo.yaml','svc.yaml','bgp-config.yaml'):
                shutil.copy2(ROOT / lab / name, directory / name)
        binary = self.root / 'bin'
        binary.mkdir()
        for tool in ('uname','id','docker','kind','clab','helm','kubectl','modprobe','container','sysctl','df'):
            path = binary / tool
            path.write_text(f'#!{sys.executable}\n' + MOCK)
            path.chmod(0o755)
        self.log = self.root / 'calls.jsonl'
        self.environment = dict(os.environ, PATH=str(binary)+os.pathsep+os.environ['PATH'], LAB_TEST_LOG=str(self.log), LAB_WAIT_SECONDS='10')
        for name in ('DOCKER_HOST','DOCKER_CONTEXT','LAB_TEST_FAIL','LAB_TEST_CLUSTERS','LAB_TEST_ENDPOINT','LAB_TEST_CONTAINERS','LAB_TEST_OS','LAB_TEST_MISSING_CRD','LAB_TEST_SECURITY'):
            self.environment.pop(name, None)

    def run_script(self, lab='bgp', script='all-in-one.sh', **environment):
        return subprocess.run([str(self.root / lab / script)], cwd='/',
                              env=dict(self.environment, **environment), capture_output=True, text=True, timeout=15)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_kind_failure_stops_before_topology_helm_and_kubernetes_mutations(self):
        result = self.run_script(LAB_TEST_FAIL='kind:create')
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertNotIn('clab', {call['tool'] for call in self.calls()})
        self.assertNotIn('helm', {call['tool'] for call in self.calls()})
        self.assertNotIn('kubectl', {call['tool'] for call in self.calls()})

    def test_topology_failure_stops_before_chart_and_service_changes(self):
        result = self.run_script(LAB_TEST_FAIL='clab:deploy')
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertNotIn('helm', {call['tool'] for call in self.calls()})
        self.assertNotIn('kubectl', {call['tool'] for call in self.calls()})

    def test_trace_prints_commands_to_stderr_and_preserves_failure_status(self):
        result = self.run_script(LAB_TRACE='1', LAB_TEST_FAIL='kind:create')
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertIn('kind create cluster', result.stderr)
        self.assertIn('lab.sh:', result.stderr)
        self.assertNotIn('kind create cluster', result.stdout)

    def test_macos_entrypoint_selects_vm_and_native_state_root_and_forwards_trace(self):
        result = subprocess.run([str(self.root/'vm.sh'),'bgp-ecmp','verify'], cwd='/',
            env=dict(self.environment, LAB_TEST_OS='Darwin', MACHINE='network-vm', LAB_TRACE='1', NETWORK_VM_ROOT='/var/tmp/network labs'),
            capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        call = next(call for call in self.calls() if call['tool']=='container')
        self.assertEqual(call['args'][:5], ['machine','run','-n','network-vm','--root'])
        self.assertIn('LAB_TRACE=1', call['args'])
        self.assertIn('NETWORK_VM_ROOT=/var/tmp/network labs', call['args'])
        self.assertIn('NETWORK_VM_LAB=bgp-ecmp', call['args'])
        self.assertIn('NETWORK_VM_ACTION=verify', call['args'])

    def test_both_labs_work_from_an_unrelated_directory_with_explicit_contexts(self):
        for lab in ('bgp','bgp-ecmp'):
            with self.subTest(lab=lab):
                self.log.unlink(missing_ok=True)
                result = self.run_script(lab)
                self.assertEqual(result.returncode, 0, result.stderr)
                name = 'cilium-' + lab
                calls = self.calls()
                create = next(call for call in calls if call['tool']=='kind' and call['args'][:2]==['create','cluster'])
                self.assertIn(name, create['args'])
                self.assertIn(str(self.root/lab/'kind.yaml'), create['args'])
                self.assertIn('--image', create['args'])
                saved = next(call for call in calls if call['tool']=='docker' and call['args'][:3]==['image','save','--platform'])
                self.assertEqual(saved['args'][3], 'linux/arm64')
                self.assertTrue(any(call['tool']=='kind' and call['args'][:2]==['load','image-archive'] for call in calls))
                helm = next(call for call in calls if call['tool']=='helm')
                self.assertIn('kind-'+name, helm['args'])
                self.assertIn(str(self.root/lab/'cilium'), helm['args'])
                for call in calls:
                    if call['tool']=='kubectl':
                        self.assertEqual(call['args'][:4], ['--kubeconfig',str(self.root/lab/'output/kubeconfig'),'--context','kind-'+name])
                crds = {call['args'][6] for call in calls if call['tool']=='kubectl' and call['args'][4:6]==['get','crd']}
                self.assertEqual(len(crds), 3)
                self.assertFalse(any(call['tool']=='kubectl' and 'create' in call['args'] for call in calls))
                self.assertEqual((self.root/lab/'output/kubeconfig').stat().st_mode & 0o777, 0o600)

    def test_macos_deploy_checks_physical_free_space_before_starting_vm(self):
        for free_kb, expected in (('1024', 1), ('20971520', 0)):
            with self.subTest(free_kb=free_kb):
                self.log.unlink(missing_ok=True)
                result = subprocess.run([str(self.root/'vm.sh'),'bgp','deploy'], cwd='/',
                    env=dict(self.environment, LAB_TEST_OS='Darwin', LAB_TEST_FREE_KB=free_kb),
                    capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(any(call['tool']=='container' for call in self.calls()), expected==0)

    def test_existing_lab_is_not_overwritten(self):
        result = self.run_script(LAB_TEST_CLUSTERS='cilium-bgp')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('already exists', result.stderr)
        self.assertFalse(any(call['tool']=='kind' and call['args'][0]=='create' for call in self.calls()))

    def test_host_limits_are_raised_when_low_and_never_lowered(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        changes = [call['args'][1] for call in self.calls() if call['tool']=='sysctl' and call['args'][0]=='-w']
        self.assertEqual(changes, ['fs.inotify.max_user_instances=8192','fs.inotify.max_user_watches=1048576'])
        self.log.unlink()
        result = self.run_script(LAB_TEST_HIGH_INOTIFY='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(call['tool']=='sysctl' and call['args'][0]=='-w' for call in self.calls()))

    def test_chart_failure_stops_before_custom_resources_and_workloads(self):
        result = self.run_script(LAB_TEST_FAIL='helm:upgrade')
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertNotIn('kubectl', {call['tool'] for call in self.calls()})

    def test_macos_and_remote_docker_are_rejected_before_resource_creation(self):
        for environment in ({'LAB_TEST_OS':'Darwin'}, {'LAB_TEST_ENDPOINT':'ssh://remote'}, {'LAB_TEST_SECURITY':'["name=rootless"]'}):
            self.log.unlink(missing_ok=True)
            result = self.run_script(**environment)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(any(call['tool']=='kind' for call in self.calls()))

    def test_missing_crds_time_out_before_applying_any_custom_resources(self):
        result = self.run_script(LAB_TEST_MISSING_CRD='1', LAB_WAIT_SECONDS='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Timed out waiting for CRD', result.stderr)
        self.assertFalse(any(call['tool']=='kubectl' and 'apply' in call['args'] for call in self.calls()))

    def test_destroy_targets_only_its_lab_and_attempts_kind_cleanup_after_clab_failure(self):
        result = self.run_script('bgp-ecmp','destroy.sh', LAB_TEST_CONTAINERS='clab-cilium-bgp-ecmp-router0', LAB_TEST_FAIL='clab:destroy')
        self.assertEqual(result.returncode, 7, result.stderr)
        deletion = next(call for call in self.calls() if call['tool']=='kind')
        self.assertEqual(deletion['args'], ['delete','cluster','--name','cilium-bgp-ecmp'])
        self.assertEqual(deletion['kubeconfig'], str(self.root/'bgp-ecmp/output/kubeconfig'))

    def test_ecmp_advertises_all_pod_cidrs_and_vip_only_from_rack1(self):
        root = ROOT / 'bgp-ecmp'
        documents = list(yaml.safe_load_all((root/'bgp-config.yaml').read_text()))
        advertisements = [item for item in documents if item['kind']=='CiliumBGPAdvertisement']
        peers = {item['metadata']['name']:item['spec']['families'][0]['advertisements'] for item in documents if item['kind']=='CiliumBGPPeerConfig'}
        for config in (item for item in documents if item['kind']=='CiliumBGPClusterConfig'):
            rack = config['spec']['nodeSelector']['matchLabels']['rack']
            selector = peers[config['spec']['bgpInstances'][0]['peers'][0]['peerConfigRef']['name']]
            selected = []
            for advertisement in advertisements:
                label = advertisement['metadata']['labels']['advertise']
                match = selector.get('matchLabels',{}).get('advertise') == label
                match |= any(label in rule['values'] for rule in selector.get('matchExpressions',[]) if rule['key']=='advertise' and rule['operator']=='In')
                if match: selected += [item['advertisementType'] for item in advertisement['spec']['advertisements']]
            self.assertIn('PodCIDR', selected)
            self.assertEqual('Service' in selected, rack=='rack1')

    def test_topology_and_kind_names_and_namespace_references_are_isolated(self):
        for lab in ('bgp','bgp-ecmp'):
            root = ROOT/lab
            config = yaml.safe_load((root/'kind.yaml').read_text())
            topo = yaml.safe_load((root/'topo.yaml').read_text())
            self.assertEqual(config['name'], 'cilium-'+lab)
            self.assertEqual(topo['name'], config['name'])
            targets = [node['network-mode'] for node in topo['topology']['nodes'].values() if 'network-mode' in node]
            self.assertEqual(len(targets), 4)
            self.assertTrue(all(target.startswith('container:'+config['name']+'-') for target in targets))
            self.assertEqual(set(targets), {'container:'+config['name']+'-'+suffix for suffix in ('control-plane','worker','worker2','worker3')})

    def test_ecmp_check_requires_both_installed_next_hops_not_just_bgp_candidates(self):
        prefix = '10.100.0.100/32'
        expected = ['10.0.3.2','10.0.4.2']
        route = dict(protocol='bgp',selected=True,installed=True,nexthops=[dict(ip=ip,fib=True) for ip in expected])
        self.assertTrue(checks.route_ready({prefix:[route]}, prefix, expected))
        route['nexthops'][1]['fib'] = False
        self.assertFalse(checks.route_ready({prefix:[route]}, prefix, expected))
        route['nexthops'][1]['fib'] = True
        route['installed'] = False
        self.assertFalse(checks.route_ready({prefix:[route]}, prefix, expected))
        self.assertFalse(checks.route_ready({}, prefix, expected))


if __name__ == '__main__':
    unittest.main()
