import { useRef, useState } from 'react';
import Results from './Results';
import { answers, result } from '../fixtures/launch-review-v1';
import sampleVideo from '../fixtures/launch-review-v1.mp4';
import './DemoSample.css';

const meta = { fileName: 'Synthetic meeting · 0:21', language: 'en' };

export default function DemoSample({ onBack }) {
  const videoRef = useRef(null);
  const [answer, setAnswer] = useState(null);

  const seek = (startMs) => {
    const video = videoRef.current;
    video.currentTime = startMs / 1000;
    video.focus();
  };

  return (
    <div className="demo-sample">
      <div className="demo-sample-nav">
        <button className="demo-sample-control" type="button" onClick={onBack}>Back to start</button>
      </div>
      <Results
        result={result}
        meta={meta}
        chat={answer ? [answer] : []}
        onAsk={(question) => setAnswer(answers.find(({ q }) => q === question))}
        presetQuestions={answers.map(({ q }) => q)}
        onSeek={seek}
        sampleMedia={(
          <>
            <p className="demo-sample-note">This silent clip displays the transcript on screen. Try three prepared answers below.</p>
            <video ref={videoRef} src={sampleVideo} controls preload="metadata" playsInline aria-label="Onboarding pilot sample video" />
          </>
        )}
      />
    </div>
  );
}
