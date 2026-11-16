// Extract a recording's audio in the browser so video uploads send only what the server uses:
// 16 kHz mono 16-bit WAV, the exact format the backend's ffmpeg step produces from every upload.
// Built-in Web Audio only; no libraries. Measured in docs/BROWSER_MEDIA_EXPERIMENT.md.

export const RATE = 16000;
const VIDEO_EXTENSIONS = ['.mp4', '.mov', '.mkv', '.webm'];
// shortcut: the whole file is read into memory to decode it; untested on phones above this size.
export const MAX_SOURCE_BYTES = 250 * 1024 * 1024;
// Below this the possible saving is under about 1 MB (a 1-minute WAV is 1.9 MB), so upload as is.
export const MIN_SOURCE_BYTES = 2 * 1024 * 1024;

const extension = (name) => name.slice(name.lastIndexOf('.')).toLowerCase();

// Videos are mostly picture bytes; oversized audio (e.g. 48 kHz stereo WAV) also shrinks a lot.
export function shouldExtract(file, maxUploadBytes) {
  const video = file.type.startsWith('video/') || VIDEO_EXTENSIONS.includes(extension(file.name));
  return (video || file.size > maxUploadBytes) && file.size > MIN_SOURCE_BYTES && file.size <= MAX_SOURCE_BYTES;
}

// Average all channels into one and keep at most maxFrames samples.
export function toMono(channels, maxFrames) {
  const frames = Math.min(channels[0].length, maxFrames);
  if (channels.length === 1) return channels[0].subarray(0, frames);
  const mono = new Float32Array(frames);
  for (const channel of channels) for (let i = 0; i < frames; i++) mono[i] += channel[i] / channels.length;
  return mono;
}

export function wavBytes(samples, rate = RATE) {
  const view = new DataView(new ArrayBuffer(44 + samples.length * 2));
  const text = (offset, value) => { for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i)); };
  text(0, 'RIFF'); view.setUint32(4, 36 + samples.length * 2, true); text(8, 'WAVEfmt ');
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  text(36, 'data'); view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, samples[i])) * 0x7fff, true);
  return new Uint8Array(view.buffer);
}

// Resolves to { file, seconds } with the first maxSeconds as WAV; rejects if the browser cannot decode it.
export async function extractAudio(file, maxSeconds) {
  const context = new OfflineAudioContext(1, RATE, RATE);
  const decoded = await context.decodeAudioData(await file.arrayBuffer());
  const channels = Array.from({ length: decoded.numberOfChannels }, (_, i) => decoded.getChannelData(i));
  const name = file.name.slice(0, file.name.lastIndexOf('.')) + '.wav';
  return {
    file: new File([wavBytes(toMono(channels, maxSeconds * RATE))], name, { type: 'audio/wav' }),
    seconds: decoded.duration,
  };
}
