// Run with node code/test_coach.cjs; no browser or API credits required.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const path = require('path');
const elements = new Map();
let requests = 0, plays = 0, stops = 0;
let nodeCount = 0;
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    checked: false, textContent: '', style: {setProperty(key,value){this[key]=value;}}, attributes: {}, children: [], scrollTop: 0,
    setAttribute(key, value) {this.attributes[key] = String(value);}, getAttribute(key){return this.attributes[key] ?? null;},
    append(...nodes){this.children.push(...nodes);},replaceChildren(...nodes){this.children=nodes;},
    classList: {toggle() {}}, querySelector() {return element('connection-label');},
    addEventListener(type, callback) {this[type] = callback;},
  });
  return elements.get(id);
}
class AudioContext {
  constructor() {this.state = 'running'; this.destination = {};}
  async resume() {}
  async decodeAudioData() {return {};}
  createBufferSource() {return {connect() {}, start() {plays++;}, stop() {stops++;}};}
}
const context = {
  document: {getElementById: element, createElement:()=>element(`node-${nodeCount++}`),createElementNS:()=>element(`node-${nodeCount++}`)}, window: {AudioContext}, setTimeout() {}, console,
  requestAnimationFrame(){return 1;},cancelAnimationFrame(){},
  fetch: async (url) => {
    if (url === '/api/voice') requests++;
    return {ok: true, json: async () => ({}), arrayBuffer: async () => new ArrayBuffer(8)};
  },
};
vm.createContext(context);
const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], context);
const flush = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  await flush(); // Let the dashboard's initial refresh finish.
  vm.runInContext(`function completed(id, score, status) { return {status:'COMPLETE', session_id:'run-a', flight_id:id, score, voice:{status, configured:true, session_id:'run-a', flight_id:id, score, audio_url:'/api/voice/run-a/'+id+'.mp3'}}; } renderVoice(completed(1,73,'idle'))`, context);
  assert.equal(requests, 0);
  element('voice-enabled').checked = true;
  await element('voice-enabled').change();
  assert.equal(requests, 1);
  // Cached audio for a different score must never play.
  vm.runInContext(`var mismatched=completed(1,73,'ready');mismatched.voice.score=42;renderVoice(mismatched)`, context);
  await flush();
  assert.equal(plays, 0);
  vm.runInContext(`renderVoice(completed(1,73,'ready'))`, context);
  await flush();
  assert.equal(plays, 1);
  vm.runInContext('renderVoice(latestData)', context);
  await flush();
  assert.equal(plays, 1);
  element('voice-enabled').checked = false;
  await element('voice-enabled').change();
  assert.equal(stops, 1);
  element('voice-enabled').checked = true;
  await element('voice-enabled').change();
  await flush();
  assert.equal(plays, 1);
  assert(!html.includes('id="voice-play"'));
  assert(!html.includes('id="coach-title"'));
  let finishDecode;
  AudioContext.prototype.decodeAudioData = () => new Promise(resolve => {finishDecode = resolve;});
  vm.runInContext(`renderVoice(completed(2,88,'ready'))`, context);
  await flush();
  vm.runInContext(`renderVoice({status:'ARMED',session_id:'run-a',flight_id:2,score:88,voice:{configured:true}})`, context);
  finishDecode({});
  await flush();
  assert.equal(plays, 1, 'Late audio must not play after the next flight is armed');
  AudioContext.prototype.decodeAudioData = async () => ({});
  vm.runInContext(`render({status:'COMPLETE',flight_id:2,session_id:'run-a',score:88,voice:{status:'idle',configured:false},frame_width:1280,frame_height:720,trajectory:[[20,300],[100,290],null,[1100,100],[1120,110]],prediction:[[1120,110],[1280,180]],forecast_endpoint:[1280,180],forecast_kind:'exit',landing_x:null})`, context);
  assert.equal(element('landing-label').textContent, 'Estimated exit');
  assert.equal(element('endpoint-label').textContent, 'Last seen');
  assert.equal(element('launch-marker').attributes.cx, '20');
  const d = element('observed-line').attributes.d;
  assert(!d.includes('NaN') && !d.includes('undefined'));
  assert.equal((d.match(/M/g) || []).length, 2);
  vm.runInContext(`render({status:'READY',trajectory:[],prediction:[],landing_x:null,voice:{}})`, context);
  assert.equal(element('launch-label').textContent, '');
  assert.equal(element('landing-label').textContent, '');
  assert.equal(element('observed-line').attributes.d, '');
  vm.runInContext(`historyFlights = [1,2,3,4,5,6].map(id=>({history_id:'saved-'+id,flight_id:id,score:80+id,airtime:1,frame_width:320,frame_height:240,trajectory:[[20,40],[30,50],[40,60]],trajectory_times:[0,.4,1],completed_at:'2026-10-10T20:00:00Z'}));renderHistory();setComparison('saved-1',true)`, context);
  assert.equal(element('history-list').children.length, 6);
  assert.equal(element('comparison-lines').children.length, 1);
  assert(element('comparison-lines').children[0].attributes.d.includes('M40,80'), 'History must scale to current camera frame');
  const livePath = element('observed-line').attributes.d;
  const requestsBeforeReplay = requests;
  vm.runInContext(`startReplay('saved-1');animateReplay(0);animateReplay(100);`, context);
  assert.equal(element('replay-bar').hidden, false);
  assert.equal(element('comparison-lines').children[0].attributes.d, 'M40,80');
  element('replay-scrub').value = '1000';
  element('replay-scrub').input();
  assert(element('comparison-lines').children[0].attributes.d.includes('L80,120'));
  assert.equal(element('observed-line').attributes.d, livePath, 'Replay must not overwrite live path');
  assert.equal(requests, requestsBeforeReplay, 'Replay must never request paid narration');
  vm.runInContext(`setComparison('saved-2',true);setComparison('saved-3',true);setComparison('saved-4',true);setComparison('saved-5',true);`, context);
  assert.equal(vm.runInContext(`setComparison('saved-6',true)`,context), false);
  element('clear-comparisons').click();
  assert.equal(element('comparison-lines').children.length, 0);
  assert.equal(element('replay-bar').hidden, true);
  console.log('Coach checks passed: automatic, once per flight, mute stops, no replay.');
  console.log('Score checks passed: mismatched score rejected, late audio cancelled.');
  console.log('Graph checks passed: invalid samples, path breaks, real launch point, exit labels, reset.');
  console.log('History checks passed: cards, overlays, coordinate scaling, replay/scrub isolation, selection limit, clear.');
})().catch(error => {console.error(error); process.exitCode = 1;});
