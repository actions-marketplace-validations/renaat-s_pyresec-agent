import subprocess, sys, time, os

os.chdir(r"C:\Users\renaa\AI AGENT DEV 2026\PYRESEC")

proc = subprocess.Popen(
    [sys.executable, "-u", "main.py"],
    stdout=open("server_live.log", "w"),
    stderr=subprocess.STDOUT,
    cwd=r"C:\Users\renaa\AI AGENT DEV 2026\PYRESEC"
)

print(f"Server started PID: {proc.pid}")
time.sleep(15)

if proc.poll() is not None:
    print(f"Server EXITED with code: {proc.returncode}")
    with open("server_live.log") as f:
        print(f.read())
else:
    print("Server still running")
    with open("server_live.log") as f:
        print(f.read())
