import { spawn } from 'child_process';
import path from 'path';

let llamaServerProcess = null;
let sdServerProcess = null;

export function startLlamaServer(aiDir) {
  if (llamaServerProcess) return;

  const serverExe = path.join(aiDir, 'llama-server.exe');
  const modelFile = path.join(aiDir, 'Llama-3.2-1B-Instruct-Q4_K_M.gguf');

  console.log(`Starting llama-server with model ${modelFile}`);

  llamaServerProcess = spawn(serverExe, [
    '-m', modelFile,
    '--port', '8080',
    '--host', '127.0.0.1',
    '-c', '2048' // Context size
  ]);

  llamaServerProcess.stdout.on('data', (data) => {
    console.log(`llama-server: ${data}`);
  });

  llamaServerProcess.stderr.on('data', (data) => {
    console.error(`llama-server err: ${data}`);
  });

  llamaServerProcess.on('close', (code) => {
    console.log(`llama-server exited with code ${code}`);
    llamaServerProcess = null;
  });
}

export function stopServers() {
  if (llamaServerProcess) {
    console.log('Stopping llama-server...');
    llamaServerProcess.kill();
    llamaServerProcess = null;
  }
  
  if (sdServerProcess) {
    console.log('Stopping sd-server...');
    sdServerProcess.kill();
    sdServerProcess = null;
  }
}
