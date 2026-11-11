// Original synthetic script. Each segment starts at the matching cut in launch-review-v1.mp4.
const segments = [
  {
    chunk_id: 'sample-01',
    start_ms: 0,
    end_ms: 7000,
    timing_precision: 'segment',
    text: 'We will launch the onboarding pilot on Tuesday with twenty volunteers.',
  },
  {
    chunk_id: 'sample-02',
    start_ms: 7000,
    end_ms: 14000,
    timing_precision: 'segment',
    text: 'Maya will send the volunteer invitations by Monday afternoon.',
  },
  {
    chunk_id: 'sample-03',
    start_ms: 14000,
    end_ms: 21000,
    timing_precision: 'segment',
    text: 'We still need to decide how long to keep the feedback recordings.',
  },
];

export const result = {
  title: 'Onboarding pilot review',
  summary: 'The team plans a Tuesday onboarding pilot with 20 volunteers. Maya will send the invitations by Monday afternoon. The retention period for feedback recordings is still open.',
  action_items: 'Maya will send the volunteer invitations by Monday afternoon.',
  key_decisions: 'Launch the onboarding pilot on Tuesday with 20 volunteers.',
  open_questions: 'How long should the team keep the feedback recordings?',
  transcript: segments.map(({ text }) => text).join('\n\n'),
};

export const answers = [
  {
    id: 'pilot-launch',
    q: 'When does the pilot launch?',
    a: 'The onboarding pilot launches on Tuesday with 20 volunteers.',
    citations: [segments[0]],
  },
  {
    id: 'pilot-invitations',
    q: 'Who will send the invitations?',
    a: 'Maya will send the volunteer invitations by Monday afternoon.',
    citations: [segments[1]],
  },
  {
    id: 'pilot-budget',
    q: 'What is the pilot budget?',
    a: 'The transcript does not say what the pilot budget is.',
    citations: [],
  },
];
