import test from 'node:test';
import assert from 'node:assert/strict';
import { MAX_SOURCE_BYTES, shouldExtract, toMono, wavBytes } from './extractAudio.js';

const LIMIT = 25 * 1024 * 1024;
const file = (name, type, size) => ({ name, type, size });

test('shouldExtract picks videos and oversized audio, within the source cap', () => {
  assert.equal(shouldExtract(file('talk.mp4', 'video/mp4', 30e6), LIMIT), true);
  assert.equal(shouldExtract(file('talk.MOV', '', 3e6), LIMIT), true);
  assert.equal(shouldExtract(file('tiny.mp4', 'video/mp4', 1e6), LIMIT), false);
  assert.equal(shouldExtract(file('talk.mp3', 'audio/mpeg', 700e3), LIMIT), false);
  assert.equal(shouldExtract(file('talk.wav', 'audio/wav', LIMIT + 1), LIMIT), true);
  assert.equal(shouldExtract(file('huge.mp4', 'video/mp4', MAX_SOURCE_BYTES + 1), LIMIT), false);
});

test('toMono averages channels and trims', () => {
  const left = Float32Array.from([1, 0.5, 0, -1]);
  const right = Float32Array.from([0, 0.5, 1, -1]);
  assert.deepEqual([...toMono([left, right], 3)], [0.5, 0.5, 0.5]);
  assert.deepEqual([...toMono([left], 2)], [1, 0.5]);
});

test('wavBytes writes a 16 kHz mono 16-bit PCM WAV', () => {
  const bytes = wavBytes(Float32Array.from([0, 1, -1, 2]));
  const view = new DataView(bytes.buffer);
  const text = (offset, length) => String.fromCharCode(...bytes.subarray(offset, offset + length));
  assert.equal(text(0, 4), 'RIFF');
  assert.equal(text(8, 8), 'WAVEfmt ');
  assert.equal(view.getUint16(22, true), 1);
  assert.equal(view.getUint32(24, true), 16000);
  assert.equal(view.getUint16(34, true), 16);
  assert.equal(view.getUint32(40, true), 8);
  assert.equal(bytes.length, 44 + 8);
  assert.deepEqual([1, 2, 3].map((i) => view.getInt16(44 + i * 2, true)), [32767, -32767, 32767]);
});
