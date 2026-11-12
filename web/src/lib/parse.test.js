import test from 'node:test';
import assert from 'node:assert/strict';
import { stripMd, toLines, toParagraphs } from './parse.js';

test('stripMd removes paired markdown markers', () => {
  assert.equal(stripMd('**Owner:** Priya'), 'Owner: Priya');
  assert.equal(stripMd('__Due date__ Friday'), 'Due date Friday');
  assert.equal(stripMd('Run `npm test` then ``a`b``'), 'Run npm test then a`b');
  assert.equal(stripMd('## Launch plan'), 'Launch plan');
});

test('stripMd keeps identifiers and unpaired markers', () => {
  assert.equal(stripMd('Edit __init__.py and __main__'), 'Edit __init__.py and __main__');
  assert.equal(stripMd('snake__case__name'), 'snake__case__name');
  assert.equal(stripMd('2 ** 3 is 8'), '2 ** 3 is 8');
  assert.equal(stripMd('a lone ` backtick'), 'a lone ` backtick');
  assert.equal(stripMd(''), '');
  assert.equal(stripMd(null), '');
});

test('toLines drops bullets, numbering and blank lines', () => {
  assert.deepEqual(toLines('- **Ship** it\n\n2. Fix `bug`\n* third\n**Owner:** Sam'),
    ['Ship it', 'Fix bug', 'third', 'Owner: Sam']);
  assert.deepEqual(toLines(''), []);
});

test('toParagraphs splits on blank lines', () => {
  assert.deepEqual(toParagraphs('One\nstill one\n\n  \n**Two**'), ['One\nstill one', 'Two']);
  assert.deepEqual(toParagraphs(undefined), []);
});
