#!/usr/bin/env python3
import argparse, copy, glob, json, os, queue, re, subprocess, sys, threading, time
from pathlib import Path
parser=argparse.ArgumentParser(description='Real kernel + C/C++ DAP smoke test; requires the selected container backend, bound sources and the VSCode C/C++ extension.')
parser.add_argument('environment', choices=('single-container','multi-container','apple-container','debian-container','one_container','multi_containers'))
parser.add_argument('--existing', action='store_true', help='Use an existing build instead of rebuilding')
parser.add_argument('--adapter', type=Path, help='Path to OpenDebugAD7')
parser.add_argument('--isolated', action='store_true', help='Apple container only: use existing artifacts in a disposable test container')
args=parser.parse_args()
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from layout import KERNEL_ROOT, REPO_ROOT, canonical
repo=REPO_ROOT
kind=canonical(args.environment)
root=KERNEL_ROOT/kind
local=json.loads((root/'output/config.local.json').read_text()) if (root/'output/config.local.json').exists() else {}
source=Path(os.environ.get('KERNEL_SOURCE',local.get('source',str(repo/'linux-source')))).resolve()
if args.isolated and kind!='apple-container':parser.error('--isolated requires apple-container')
launch=json.loads((root/'.vscode/launch.json').read_text())['configurations'][1 if args.existing or args.isolated else 0]
config=copy.deepcopy(launch)
for key in ('type','preLaunchTask','postDebugTask'): config.pop(key,None)
def expand(value):
    if isinstance(value,str): return value.replace('${workspaceFolder:kernel-config}',str(root)).replace('${workspaceFolder:kernel-source}',str(source))
    if isinstance(value,list): return [expand(item) for item in value]
    if isinstance(value,dict): return {key:expand(item) for key,item in value.items()}
    return value
config=expand(config)
config['logging']={'engineLogging':True}
tasks={task['label']:task for task in json.loads((root/'.vscode/tasks.json').read_text())['tasks']}
prepare=tasks[launch['preLaunchTask']]['args']
adapters=glob.glob(str(Path.home()/'.vscode/extensions/ms-vscode.cpptools-*/debugAdapters/bin/OpenDebugAD7'))
adapter=str(args.adapter) if args.adapter else (adapters[0] if adapters else None)
if not adapter: raise SystemExit('Install the VSCode C/C++ extension, or provide --adapter /path/to/OpenDebugAD7')
if not os.access(adapter,os.X_OK): raise SystemExit('The supplied OpenDebugAD7 must be executable')
output=root/'output'
isolated=None
console_command=[str(root/'dev.sh'),'console']
def cleanup():
    if isolated:isolated.cleanup()
    else:subprocess.run([str(root/'dev.sh'),*tasks[launch['postDebugTask']]['args']],check=True)
if args.isolated:
    from isolated_apple import IsolatedApple
    isolated=IsolatedApple(root,source)
    output=isolated.output
    isolated.prepare(config)
    console_command=isolated.exec_command('python3','/scripts/kernel/qemu.py','console',interactive=True)
else:
    subprocess.run([str(root/'dev.sh'),*prepare],check=True,stdout=open(output/'dap-prepare.log','w'),stderr=subprocess.STDOUT)
try:
    process=subprocess.Popen([adapter],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
except OSError:
    cleanup()
    raise
messages=queue.Queue();trace=[];sequence=0
console=None

def reader():
    try:
        while True:
            headers={}
            while True:
                line=process.stdout.readline()
                if not line: raise EOFError()
                if line==b'\r\n':break
                key,value=line.decode().split(':',1);headers[key.lower()]=value.strip()
            messages.put(json.loads(process.stdout.read(int(headers['content-length']))))
    except Exception as error:messages.put({'reader_error':str(error)})
threading.Thread(target=reader,daemon=True).start()
def send(command,arguments):
    global sequence
    sequence+=1
    data=json.dumps(dict(seq=sequence,type='request',command=command,arguments=arguments)).encode()
    process.stdin.write(f'Content-Length: {len(data)}\r\n\r\n'.encode()+data);process.stdin.flush()
    return sequence

def until(predicate,seconds=60):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        message=messages.get(timeout=max(.1,deadline-time.monotonic()))
        trace.append(message)
        if message.get('type')=='response' and not message.get('success',True):raise RuntimeError(message)
        if 'reader_error' in message:raise RuntimeError(message)
        if predicate(message):return message
    raise TimeoutError()
try:
    request=send('initialize',dict(adapterID='cppdbg',clientID='kernel-workspace-smoke',linesStartAt1=True,columnsStartAt1=True,pathFormat='path',supportsRunInTerminalRequest=False))
    until(lambda message:message.get('request_seq')==request)
    send(config.get('request','launch'),config)
    until(lambda message:message.get('event')=='initialized')
    send('configurationDone',{})
    stopped=until(lambda message:message.get('event')=='stopped')
    assert stopped['body']['reason']=='breakpoint',stopped
    assert not stopped['body'].get('text'),stopped
    thread=stopped['body']['threadId']
    request=send('stackTrace',dict(threadId=thread,startFrame=0,levels=5))
    frames=until(lambda message:message.get('request_seq')==request)['body']['stackFrames']
    assert any('start_kernel' in frame['name'] for frame in frames),frames
    frame=next(frame for frame in frames if 'start_kernel' in frame['name'])
    assert frame['source']['path']==str(source/'init/main.c'),frame
    print(kind+': start_kernel stopped as a normal breakpoint; source mapping passed',flush=True)
    request=send('evaluate',dict(expression='init_task.pid',frameId=frame['id'],context='watch'))
    evaluated=until(lambda message:message.get('request_seq')==request)
    assert evaluated['body']['result']=='0',evaluated
    request=send('next',dict(threadId=thread))
    until(lambda message:message.get('event')=='stopped')
    print(kind+': kernel variable inspection and single-step passed',flush=True)
    request=send('continue',dict(threadId=thread))
    until(lambda message:message.get('request_seq')==request)
    deadline=time.monotonic()+70
    logfile=output/'console.log'
    while 'KERNEL_DEBUG_READY' not in logfile.read_text(errors='replace'):
        if time.monotonic()>deadline:raise RuntimeError(logfile.read_text(errors='replace')[-6000:])
        time.sleep(.25)
    console=subprocess.Popen(console_command,stdin=subprocess.PIPE,stdout=open(output/'console-smoke.log','wb'),stderr=subprocess.PIPE)
    deadline=time.monotonic()+15
    while not re.search(rb'\r?\nKERNEL_DEBUG_OK\r?\n',logfile.read_bytes()):
        if time.monotonic()>deadline:raise RuntimeError(logfile.read_text(errors='replace')[-5000:])
        console.stdin.write(b"printf 'KERNEL_%s\\n' DEBUG_OK\r");console.stdin.flush();time.sleep(1)
    console.stdin.write(b"ip -4 addr show dev eth0 && ping -c 1 -W 3 10.0.2.2 && printf 'KERNEL_NETWORK_%s\\n' OK\r")
    console.stdin.flush()
    deadline=time.monotonic()+15
    while not re.search(rb'\r?\nKERNEL_NETWORK_OK\r?\n',logfile.read_bytes()):
        if time.monotonic()>deadline:raise RuntimeError('Guest network check failed:\n'+logfile.read_text(errors='replace')[-5000:])
        time.sleep(.25)
    # A breakpoint added while the guest is idle needs a hidden internal pause.
    # It must auto-resume without a user-visible Interrupt exception.
    breakpoint_source=dict(path=str(source/'net/ipv4/tcp_ipv4.c'))
    for lines in ([206],[],[206]):
        beginning=len(trace)
        request=send('setBreakpoints',dict(source=breakpoint_source,breakpoints=[dict(line=line) for line in lines]))
        response=until(lambda message:message.get('request_seq')==request)
        assert all(item['verified'] for item in response['body']['breakpoints']),response
        deadline=time.monotonic()+1
        while time.monotonic()<deadline:
            try:message=messages.get(timeout=.1)
            except queue.Empty:continue
            trace.append(message)
        assert not any('<PENDING>' in message.get('body',{}).get('output','') for message in trace[beginning:]),trace[beginning:]
        assert not any(message.get('event')=='stopped' for message in trace[beginning:]),trace[beginning:]
        if isolated:assert isolated.status()['vm_state']=='running'
    print(kind+': adding, removing and re-adding live source breakpoints auto-resumed without exception',flush=True)
    console.stdin.write(b"curl -4 -s --connect-timeout 10 --max-time 20 http://10.0.2.2:9/; printf 'KERNEL_TCP_%s\\n' DONE\r")
    console.stdin.flush()
    stopped=until(lambda message:message.get('event')=='stopped')
    assert stopped['body']['reason']=='breakpoint',stopped
    thread=stopped['body']['threadId']
    request=send('stackTrace',dict(threadId=thread,startFrame=0,levels=3))
    frames=until(lambda message:message.get('request_seq')==request)['body']['stackFrames']
    assert any('tcp_v4_connect' in frame['name'] for frame in frames),frames
    print(kind+': live TCP source breakpoint hit the requested function',flush=True)
    request=send('continue',dict(threadId=thread))
    until(lambda message:message.get('request_seq')==request)
    deadline=time.monotonic()+25
    while not re.search(rb'\r?\nKERNEL_TCP_DONE\r?\n',logfile.read_bytes()):
        if time.monotonic()>deadline:raise RuntimeError('TCP command did not finish after continuing')
        time.sleep(.1)
    if kind == 'debian-container':
        console.stdin.write(b"printf 'KERNEL_DEBUG_PERSISTENCE_OK\\n' > /root/.kernel-debug-disconnect-test; printf 'KERNEL_DISK_WRITE_%s\\n' OK\r")
        console.stdin.flush()
        deadline=time.monotonic()+10
        while not re.search(rb'\r?\nKERNEL_DISK_WRITE_OK\r?\n',logfile.read_bytes()):
            if time.monotonic()>deadline:raise RuntimeError('Persistent guest write did not finish')
            time.sleep(.1)
    console.stdin.write(b'\x1d');console.stdin.flush();console.communicate(timeout=10)
    assert console.returncode==0
    print(kind+': guest rootfs boot, console command and networking passed',flush=True)
    request=send('disconnect',dict(terminateDebuggee=config.get('request')!='attach'))
    until(lambda message:message.get('request_seq')==request)
    process.wait(timeout=10)
finally:
    if console and console.poll() is None:console.terminate();console.wait(timeout=5)
    if process.poll() is None:
        process.terminate()
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired: process.kill();process.wait()
    cleanup()
    (output/'dap-smoke.json').write_text(json.dumps(trace,indent=2))
if kind == 'debian-container':
    with open(output/'rootfs.ext4','rb') as disk:
        disk.seek(1024+58)
        assert int.from_bytes(disk.read(2),'little') & 1, 'Debugger terminated the guest without clean filesystem shutdown'
    print(kind+': debugger disconnect preserved a clean persistent filesystem',flush=True)
print(kind+': debug cleanup passed',flush=True)
