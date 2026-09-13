import fs from 'fs';
import path from 'path';
import axios from 'axios';
import extractZip from 'extract-zip';

export async function downloadFile(url, dest, onProgress) {
  if (fs.existsSync(dest)) {
    return true; // Already downloaded
  }

  const dir = path.dirname(dest);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }

  const writer = fs.createWriteStream(dest);

  try {
    const response = await axios({
      url,
      method: 'GET',
      responseType: 'stream',
    });

    const totalLength = response.headers['content-length'];

    let downloaded = 0;
    response.data.on('data', (chunk) => {
      downloaded += chunk.length;
      if (totalLength && onProgress) {
        const percentage = Math.round((downloaded / totalLength) * 100);
        onProgress(percentage);
      }
    });

    response.data.pipe(writer);

    return new Promise((resolve, reject) => {
      writer.on('finish', resolve);
      writer.on('error', reject);
    });
  } catch (error) {
    fs.unlinkSync(dest); // Delete partial file
    throw error;
  }
}

export async function extractFile(zipPath, destDir) {
  try {
    await extractZip(zipPath, { dir: destDir });
  } catch (err) {
    throw err;
  }
}
