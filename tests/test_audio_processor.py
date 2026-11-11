import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from backend.utils import audio_processor as audio


class AudioSafetyTests(unittest.TestCase):
    def test_invalid_media_has_safe_validation_error(self):
        with patch.object(audio.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stdout=b'601')):
            with self.assertRaises(audio.MediaValidationError):
                audio.chunk_streaming('/tmp/input.mp4')

    def test_blank_duration_setting_uses_default(self):
        with patch.dict(os.environ, {'MAX_MEDIA_SECONDS': ''}):
            self.assertEqual(audio._max_seconds(), 120)

    def test_blank_download_size_uses_default(self):
        with tempfile.TemporaryDirectory() as root, patch.object(audio.tempfile, 'tempdir', root), \
                patch.dict(os.environ, {'ENABLE_YOUTUBE': 'true', 'MAX_DOWNLOAD_MB': ''}), \
                patch.object(audio.yt_dlp, 'YoutubeDL') as client:
            client.return_value.__enter__.return_value.extract_info.return_value = {'duration': 601}
            with self.assertRaises(ValueError):
                audio.download_youtube_audio('https://youtu.be/abc')
            self.assertEqual(client.call_args.args[0]['max_filesize'], 25 * 1024 * 1024)

    def test_invalid_durations_are_rejected_before_conversion(self):
        for duration in ('601', 'NaN', 'inf', 'N/A', '0'):
            with self.subTest(duration=duration), patch.dict(os.environ, {'MAX_MEDIA_SECONDS': '600'}), patch.object(audio.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stdout=duration.encode())) as run:
                with self.assertRaises((ValueError, RuntimeError)):
                    audio.chunk_streaming('/tmp/input.mp4')
                self.assertEqual(run.call_count, 1)

    def test_subprocesses_are_bounded_and_local_only(self):
        calls = []
        def run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            if len(calls) == 1:
                return subprocess.CompletedProcess(cmd, 0, stdout=b'5')
            open(cmd[-1].replace('%03d', '000'), 'wb').close()
            return subprocess.CompletedProcess(cmd, 0)
        with patch.object(audio.subprocess, 'run', side_effect=run):
            chunks, directory = audio.chunk_streaming('/tmp/input.mp4')
        self.addCleanup(audio.cleanup, [directory])
        self.assertTrue(chunks)
        for cmd, kwargs in calls:
            self.assertEqual(cmd[cmd.index('-protocol_whitelist') + 1], 'file,pipe')
            self.assertGreater(kwargs['timeout'], 0)

    def test_timeout_removes_chunk_directory(self):
        with tempfile.TemporaryDirectory() as root, patch.object(audio.tempfile, 'tempdir', root), patch.object(audio.subprocess, 'run', side_effect=[subprocess.CompletedProcess([], 0, stdout=b'5'), subprocess.TimeoutExpired('ffmpeg', 1)]):
            with self.assertRaises(subprocess.TimeoutExpired):
                audio.chunk_streaming('/tmp/input.mp4')
            self.assertEqual(os.listdir(root), [])

    def test_youtube_disabled_and_invalid_urls_never_download(self):
        urls = ['https://youtube.com/watch?v=x', 'http://youtube.com/watch?v=x', 'https://youtube.com:443/watch?v=x', 'https://youtube.com@localhost/watch?v=x', 'https://evil.example/video']
        for url in urls:
            with self.subTest(url=url), patch.dict(os.environ, {'ENABLE_YOUTUBE': 'false'}), patch.object(audio.yt_dlp, 'YoutubeDL') as client:
                with self.assertRaises(ValueError):
                    audio.process_input(url)
                client.assert_not_called()

    def test_enabled_youtube_validates_host_and_rejects_playlists(self):
        with patch.dict(os.environ, {'ENABLE_YOUTUBE': 'true'}):
            self.assertEqual(audio.validate_youtube_url('https://youtu.be/abc'), 'https://youtu.be/abc')
            for url in ('http://youtube.com/watch?v=x', 'https://youtube.com:443/watch?v=x',
                        'https://youtube.com@localhost/x', 'https://127.0.0.1/x',
                        'https://youtube.com/playlist?list=abc', 'https://youtube.com/watch?v=x&list=abc'):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    audio.validate_youtube_url(url)

    def test_download_failure_removes_private_directory(self):
        with tempfile.TemporaryDirectory() as root, patch.object(audio.tempfile, 'tempdir', root), \
                patch.dict(os.environ, {'ENABLE_YOUTUBE': 'true'}), patch.object(audio.yt_dlp, 'YoutubeDL') as client:
            client.return_value.__enter__.return_value.extract_info.side_effect = RuntimeError('failed')
            with self.assertRaises(RuntimeError):
                audio.download_youtube_audio('https://youtube.com/watch?v=x')
            self.assertEqual(os.listdir(root), [])

    def test_youtube_challenge_offers_upload_without_using_cookies(self):
        with tempfile.TemporaryDirectory() as root, patch.object(audio.tempfile, 'tempdir', root), \
                patch.dict(os.environ, {'ENABLE_YOUTUBE': 'true', 'YT_DLP_COOKIES_PATH': root}), \
                patch.object(audio.yt_dlp, 'YoutubeDL') as client:
            downloader = client.return_value.__enter__.return_value
            downloader.extract_info.side_effect = audio.yt_dlp.utils.DownloadError("Sign in to confirm you're not a bot")
            with self.assertRaisesRegex(audio.MediaValidationError, 'Upload an audio or video file'):
                audio.download_youtube_audio('https://youtu.be/abc')
            self.assertNotIn('cookiefile', client.call_args.args[0])
            self.assertEqual(os.listdir(root), [])

    def test_youtube_metadata_rejects_live_and_overlong_before_download(self):
        for info in ({'duration': 601}, {'duration': 4, 'is_live': True}, {'duration': None}, {'_type': 'playlist'}):
            with self.subTest(info=info), tempfile.TemporaryDirectory() as root, \
                    patch.object(audio.tempfile, 'tempdir', root), patch.dict(os.environ, {'ENABLE_YOUTUBE': 'true'}), \
                    patch.object(audio.yt_dlp, 'YoutubeDL') as client:
                downloader = client.return_value.__enter__.return_value
                downloader.extract_info.return_value = info
                with self.assertRaises(ValueError):
                    audio.download_youtube_audio('https://youtube.com/watch?v=x')
                downloader.process_ie_result.assert_not_called()
                self.assertEqual(os.listdir(root), [])

    def test_download_size_hook_cleans_partial_file(self):
        with tempfile.TemporaryDirectory() as root, patch.object(audio.tempfile, 'tempdir', root), \
                patch.dict(os.environ, {'ENABLE_YOUTUBE': 'true', 'MAX_DOWNLOAD_MB': '1'}), \
                patch.object(audio.yt_dlp, 'YoutubeDL') as client:
            downloader = client.return_value.__enter__.return_value
            downloader.extract_info.return_value = {'duration': 5}
            def download(info, download):
                options = client.call_args.args[0]
                with open(os.path.join(os.path.dirname(options['outtmpl']), 'partial'), 'wb') as output:
                    output.write(b'partial')
                options['progress_hooks'][0]({'downloaded_bytes': 1048577})
            downloader.process_ie_result.side_effect = download
            with self.assertRaises(ValueError):
                audio.download_youtube_audio('https://youtu.be/abc')
            self.assertEqual(os.listdir(root), [])

    def test_missing_ffmpeg_removes_chunk_directory(self):
        with tempfile.TemporaryDirectory() as root, patch.object(audio.tempfile, 'tempdir', root), \
                patch.object(audio.subprocess, 'run', side_effect=[subprocess.CompletedProcess([], 0, stdout=b'5'), FileNotFoundError('ffmpeg')]):
            with self.assertRaises(FileNotFoundError):
                audio.chunk_streaming('/tmp/input.mp4')
            self.assertEqual(os.listdir(root), [])

    def test_download_directory_removed_when_processing_fails(self):
        with tempfile.TemporaryDirectory() as root:
            directory = os.path.join(root, 'download')
            os.mkdir(directory)
            path = os.path.join(directory, 'audio.webm')
            open(path, 'wb').close()
            with patch.object(audio, 'download_youtube_audio', return_value=path), patch.object(audio, 'chunk_streaming', side_effect=RuntimeError('bad media')):
                with self.assertRaises(RuntimeError):
                    audio.process_input('https://youtube.com/watch?v=x')
            self.assertFalse(os.path.exists(directory))


if __name__ == '__main__':
    unittest.main()
