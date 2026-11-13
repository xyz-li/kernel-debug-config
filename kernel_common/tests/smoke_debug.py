#!/usr/bin/env python3
import argparse, copy, glob, json, os, queue, re, subprocess, sys, threading, time
from pathlib import Path
parser=argparse.ArgumentParser(description='Real kernel + C/C++ DAP smoke test; requires Docker, bound sources and the VSCode C/C++ extension.')
parser.add_argument('environment', choices=('one_container','multi_containers'))
parser.add_argument('--existing', action='store_true', help='Use an existing build instead of rebuilding')
parser.add_argument('--adapter', type=Path, help='Path to OpenDebugAD7')
args=parser.parse_args()
repo=Path(__file__).resolve().parents[2]
kind=args.environment
root=repo/kind
local=json.loads((root/'output/config.local.json').read_text()) if (root/'output/config.local.json').exists() else {}
source=Path(os.environ.get('KERNEL_SOURCE',local.get('source',str(repo/'linux-source')))).resolve()
launch=json.loads((root/'.vscode/launch.json').read_text())['configurations'][1 if args.existing else 0]
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
subprocess.run([str(root/'dev.sh'),*prepare],check=True,stdout=open(root/'output/dap-prepare.log','w'),stderr=subprocess.STDOUT)
try:
    process=subprocess.Popen([adapter],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
except OSError:
    subprocess.run([str(root/'dev.sh'),'stop'],check=True)
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
    send('launch',config)
    until(lambda message:message.get('event')=='initialized')
    send('configurationDone',{})
    stopped=until(lambda message:message.get('event')=='stopped')
    thread=stopped['body']['threadId']
    request=send('stackTrace',dict(threadId=thread,startFrame=0,levels=5))
    frames=until(lambda message:message.get('request_seq')==request)['body']['stackFrames']
    assert any('start_kernel' in frame['name'] for frame in frames),frames
    frame=next(frame for frame in frames if 'start_kernel' in frame['name'])
    assert frame['source']['path']==str(source/'init/main.c'),frame
    print(kind+': real Linux start_kernel breakpoint and source mapping passed',flush=True)
    request=send('evaluate',dict(expression='init_task.pid',frameId=frame['id'],context='watch'))
    evaluated=until(lambda message:message.get('request_seq')==request)
    assert evaluated['body']['result']=='0',evaluated
    request=send('next',dict(threadId=thread))
    until(lambda message:message.get('event')=='stopped')
    print(kind+': kernel variable inspection and single-step passed',flush=True)
    request=send('continue',dict(threadId=thread))
    until(lambda message:message.get('request_seq')==request)
    deadline=time.monotonic()+70
    logfile=root/'output/console.log'
    while 'KERNEL_DEBUG_READY' not in logfile.read_text(errors='replace'):
        if time.monotonic()>deadline:raise RuntimeError(logfile.read_text(errors='replace')[-6000:])
        time.sleep(.25)
    console=subprocess.Popen([str(root/'dev.sh'),'console'],stdin=subprocess.PIPE,stdout=open(root/'output/console-smoke.log','wb'),stderr=subprocess.PIPE)
    deadline=time.monotonic()+15
    while not re.search(rb'\r?\nKERNEL_DEBUG_OK\r?\n',logfile.read_bytes()):
        if time.monotonic()>deadline:raise RuntimeError(logfile.read_text(errors='replace')[-5000:])
        console.stdin.write(b"printf 'KERNEL_%s\\n' DEBUG_OK\r");console.stdin.flush();time.sleep(1)
    console.stdin.write(b'\x1d');console.stdin.flush();console.communicate(timeout=10)
    assert console.returncode==0
    print(kind+': generated Alpine rootfs boot and console command passed',flush=True)
    request=send('disconnect',dict(terminateDebuggee=True))
    until(lambda message:message.get('request_seq')==request)
    process.wait(timeout=10)
finally:
    if console and console.poll() is None:console.terminate();console.wait(timeout=5)
    if process.poll() is None:
        process.terminate()
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired: process.kill();process.wait()
    subprocess.run([str(root/'dev.sh'),*tasks[launch['postDebugTask']]['args']],check=True)
    (root/'output/dap-smoke.json').write_text(json.dumps(trace,indent=2))
print(kind+': debug cleanup passed',flush=True)
