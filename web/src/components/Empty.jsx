import { useState } from 'react';
import { humanSize } from '../lib/parse';

const ACCEPT = '.mp3,.wav,.m4a,.mp4,.mov,.mkv,.webm,.aac,.ogg,.flac';
const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

export default function Empty({ mode, submitting, onAnalyse }) {
  const [acknowledged, setAcknowledged] = useState(false);
  const [file, setFile] = useState(null);
  const [inviteCode, setInviteCode] = useState('');
  const [sizeError, setSizeError] = useState('');
  const invited = mode === 'invited';
  const canAnalyse = !submitting && acknowledged && file && (!invited || inviteCode.trim());

  const chooseFile = (event) => {
    const selected = event.target.files?.[0] || null;
    if (selected?.size > MAX_UPLOAD_BYTES || selected?.size === 0) {
      setFile(null);
      setSizeError(selected.size ? `“${selected.name}” is ${humanSize(selected.size)}. Choose a file up to 10 MiB.` : 'Choose a file that contains audio.');
      event.target.value = '';
      return;
    }
    setSizeError('');
    setFile(selected);
  };

  return (
    <form className="demo-panel demo-upload" onSubmit={(event) => {
      event.preventDefault();
      if (!canAnalyse) return;
      onAnalyse({ file, inviteCode: invited ? inviteCode.trim() : undefined });
      setInviteCode('');
    }}>
      <h1>Analyze your own clip</h1>
      <p id="upload-limits">Upload an English audio or video file up to 10 MiB and 120 seconds.</p>
      <label htmlFor="clip-upload">Audio or video file</label>
      <input id="clip-upload" type="file" accept={ACCEPT} onChange={chooseFile} disabled={submitting}
        aria-describedby={sizeError ? 'upload-limits upload-error' : 'upload-limits'} aria-invalid={!!sizeError} />
      {sizeError && <p id="upload-error" role="alert">{sizeError}</p>}
      {invited && (
        <>
          <label htmlFor="demo-invite">Invite code</label>
          <input id="demo-invite" type="password" autoComplete="off" value={inviteCode}
            onChange={(event) => setInviteCode(event.target.value)} disabled={submitting} />
        </>
      )}
      <p id="demo-privacy">
        Use synthetic or public, non-personal material. Audio is sent to a third-party transcription provider.
        Transcript redaction can miss sensitive details and leaves names in place.
      </p>
      <label className="demo-checkbox">
        <input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)}
          aria-describedby="demo-privacy" disabled={submitting} />
        I will only submit synthetic or public, non-personal material.
      </label>
      <button className="demo-button" type="submit" disabled={!canAnalyse}>
        {submitting ? 'Uploading…' : 'Analyze clip'}
      </button>
    </form>
  );
}
