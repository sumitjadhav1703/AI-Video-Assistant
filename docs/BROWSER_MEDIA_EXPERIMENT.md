# Browser media preprocessing experiment

**Decision (2026-11-11): do not enable browser preprocessing.** This isolated experiment proves worker-based extraction works for three synthetic files on one desktop browser, but does not establish a user benefit or compatibility on lower-powered devices. The native streaming upload path remains the default. No app code or runtime dependencies were changed.

## Method and results

On an arm64 Mac using Playwright's Chrome 157 and native FFmpeg 9.0.2, a temporary loopback HTTP server served the upstream single-thread `@ffmpeg/ffmpeg` 0.12.15 wrapper and `@ffmpeg/core` 0.12.10. The wrapper runs FFmpeg in a Web Worker. Each file was a synthetic 160x90, 5 fps solid blue H.264 video with a 16 kHz sine-wave AAC audio track, generated locally. One run each; all inputs were under 25 MiB. Browser output was mono 16 kHz MP3 at 48 kbps. These exceptionally compressible videos and tones are not representative video or speech.

| Duration | Video bytes | Browser MP3 bytes | Worker extraction | Native MP3 extraction | Native video to WAV | Native MP3 to WAV |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 30 s | 186,356 | 180,940 | 158 ms | 125 ms | 39 ms | 41 ms |
| 2 min | 744,681 | 720,940 | 229 ms | 231 ms | 55 ms | 62 ms |
| 10 min | 3,722,557 | 3,600,868 | 1,025 ms | 1,039 ms | 145 ms | 192 ms |

Native timings include process startup and round to milliseconds; conversions used `-vn -ac 1 -ar 16000`, and MP3 additionally used `-c:a libmp3lame -b:a 48k`. WAV measurements approximate backend conversion, but omit its probing and segment muxer and are not full API timings. Native MP3 was separately encoded and then used for the audio-to-WAV measurement; the browser output was not fed back to the backend. These numbers are single observations, not a performance comparison across machines. The browser writes the input into the worker before execution; measured copy calls took 0.2–0.8 ms. The wrapper transfers the typed array, detaching it, so input sizes above come from the filesystem rather than the detached array.

The core loaded in 143 ms from loopback, including worker/core initialization. That is **not** a cold internet download measurement. The core wasm file is 32,232,419 bytes, plus approximately 112 kB of core JavaScript and wrapper files; actual transfer depends on compression, caching and hosting. There was no measured upload, backend API round trip, energy or peak memory; no lower-powered device or alternative browser was tested. No ASR quality, codecs beyond this fixture, cancellation, browser memory pressure, or concurrent load was evaluated. The prototype holds media in the worker filesystem and is not a production memory design. Consequently no end-to-end speed or audio quality claim follows.

The [official FAQ](https://github.com/ffmpegwasm/ffmpeg.wasm/blob/main/apps/website/docs/faq.md) distinguishes the MIT wrapper from core and its external libraries. The [single-thread core package](https://github.com/ffmpegwasm/ffmpeg.wasm/blob/main/packages/core/package.json) declares GPL-2.0-or-later; a full source, bundled-library and distribution compliance review is required before shipping it. The [official performance page](https://ffmpegwasm.netlify.app/docs/performance/) also notes the cost relative to native FFmpeg. Measured artifacts were npm release tarballs (not checked into this repository):

- `@ffmpeg/ffmpeg@0.12.15`: SHA-256 `c8a23365fb39b46d3d1d9baa2e74b522d00ce5d57e8b20471ad2665eaad38e3e`.
- `@ffmpeg/core@0.12.10`: SHA-256 `d00089ce82e1bdf637ddbe42e0c3d41a1ba8cf4c9e825e7fa4d0bb970e844bd4`.

## Reproduce the worker experiment

Use a disposable directory, public npm access, native FFmpeg with libx264/AAC, and a browser; do not install these packages in `web/`. Verify the hashes above before extracting the tarballs. The following server binds only to loopback. The synthetic files and packages are deliberately kept outside the project.

```sh
mkdir -p /tmp/ava-browser-bench && cd /tmp/ava-browser-bench
npm pack @ffmpeg/ffmpeg@0.12.15 @ffmpeg/core@0.12.10 --ignore-scripts
shasum -a 256 ffmpeg-*.tgz
mkdir -p ffmpeg core
tar -xzf ffmpeg-ffmpeg-0.12.15.tgz -C ffmpeg --strip-components=1
tar -xzf ffmpeg-core-0.12.10.tgz -C core --strip-components=1
for n in 30 120 600; do
  ffmpeg -f lavfi -i 'color=c=blue:s=160x90:r=5' -f lavfi \
    -i 'sine=frequency=440:sample_rate=16000' -t "$n" \
    -c:v libx264 -preset ultrafast -c:a aac -b:a 48k -shortest "$n.mp4"
done
cp /path/to/AI-Video-Assistant/scripts/browser-media-experiment/index.html .
python3 -m http.server 8768 --bind 127.0.0.1
```

Open `http://127.0.0.1:8768/`; the page reports initialization, input bytes, write time, extraction time, and output bytes. Stop the server afterward. Test only local synthetic inputs. For any future decision, use representative licensed media and speech, measure cold/warm download, peak memory, end-to-end upload and backend time over realistic network speeds, run lower-powered devices and supported browsers, validate transcription quality, and design cancellation and fallback. A user can instead prepare audio locally with native FFmpeg and use the existing audio upload; native FFmpeg remains the server fallback.
