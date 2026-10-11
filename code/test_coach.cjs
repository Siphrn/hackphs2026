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
    removeAttribute(key){delete this[key];delete this.attributes[key];},pause(){this.paused=true;},load(){},showModal(){this.open=true;},close(){this.open=false;this.onClose?.();},
    append(...nodes){this.children.push(...nodes);},replaceChildren(...nodes){this.children=nodes;},
    replaceWith(node){this.replacement=node;},focus(){},select(){},setCustomValidity(){},reportValidity(){},setPointerCapture(){},releasePointerCapture(){},closest(){return this;},remove(){},getBoundingClientRect(){return {left:0,right:220,top:200,bottom:400};},
    classList: {toggle() {}}, querySelector() {return element('connection-label');},
    addEventListener(type, callback) {this[type === 'close' ? 'onClose' : type] = callback;},
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
  document: {body:element('body'),getElementById: element, createElement:()=>element(`node-${nodeCount++}`),createElementNS:()=>element(`node-${nodeCount++}`)}, window: {AudioContext,innerWidth:1280,innerHeight:720,scrollBy(){}}, setTimeout() {}, console,
  requestAnimationFrame(){return 1;},cancelAnimationFrame(){},
  fetch: async (url, options) => {
    if (url === '/api/voice') requests++;
    return {ok: true, json: async () => url === '/api/history/rename' ? {name:JSON.parse(options.body).name} : ({}), arrayBuffer: async () => new ArrayBuffer(8)};
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
  const nameButton = element('history-list').children[0].children[0].children[0];
  nameButton.click();
  const editor = nameButton.replacement;
  assert.equal(editor.attributes['aria-label'], 'Flight name');
  const listBeforePoll = element('history-list').children;
  vm.runInContext('renderHistory()', context);
  assert.equal(element('history-list').children, listBeforePoll, 'Polling must preserve active editor');
  editor.value = 'Wind Rider';
  editor.keydown({key:'Enter',preventDefault(){}});
  await flush();
  assert.equal(vm.runInContext('historyFlights[0].name',context), 'Wind Rider');
  const renamedButton = element('history-list').children[0].children[0].children[0];
  renamedButton.click();
  renamedButton.replacement.value = 'Cancelled';
  renamedButton.replacement.keydown({key:'Escape',preventDefault(){}});
  assert.equal(vm.runInContext('historyFlights[0].name',context), 'Wind Rider');
  element('history-toggle').setAttribute('aria-expanded','true');
  element('history-toggle').click();
  assert.equal(element('history-toggle').getAttribute('aria-expanded'),'false');
  assert.equal(element('history-body').inert,true);
  assert(html.includes('prefers-reduced-motion'));
  let profilePosts = [];
  context.fetch = async (url, options) => {
    const body = JSON.parse(options.body);
    profilePosts.push(body);
    return {ok:true, json:async()=>({profiles:[{id:'dart',name:'Dart'},{id:'glider',name:'Glider'}],active_profile_id:'dart'})};
  };
  vm.runInContext(`planeProfiles=[{id:'dart',name:'Dart'},{id:'glider',name:'Glider'}];activeProfileId='dart';historyFlights[0].profile_id='dart';renderProfiles();renderHistory()`, context);
  assert.equal(element('plane-list').children.length,2);
  assert.equal(element('next-plane').value,'dart');
  // Drag the first plane onto the second.
  const firstGrip = element('plane-list').children[0].children[0];
  context.document.elementFromPoint = () => element('plane-list').children[1];
  firstGrip.pointerdown({button:0,pointerId:1,preventDefault(){}});
  firstGrip.pointermove({clientX:10,clientY:10});
  firstGrip.pointerup({pointerId:1});
  await flush();
  assert.deepEqual(profilePosts[0].order,['glider','dart']);
  const profileSelect = element('history-list').children[0].children[3].children[1].children[2];
  profileSelect.value = 'glider';
  await profileSelect.change();
  assert.equal(vm.runInContext('historyFlights[0].profile_id',context),'glider');
  element('plane-filter').change({target:{value:'glider'}});
  assert.equal(element('history-list').children.length,1);
  assert.equal(element('history-count').textContent,1);
  element('plane-filter').change({target:{value:'all'}});
  assert.equal(element('history-list').children.length,6);
  const flightGrip = element('history-list').children[0].children[4];
  context.document.elementFromPoint = () => element('flight-drop-options').children[1];
  flightGrip.pointerdown({button:0,pointerId:2,clientX:100,clientY:600,preventDefault(){}});
  const cardsDuringDrag = element('history-list').children;
  vm.runInContext('renderHistory()',context);
  assert.equal(element('history-list').children,cardsDuringDrag,'Polling must preserve flight dragging');
  flightGrip.pointermove({clientX:100,clientY:250});
  await flightGrip.pointerup({pointerId:2});
  assert.equal(profilePosts.at(-1).action,'assign');
  assert.equal(profilePosts.at(-1).profile_id,'dart');
  assert.equal(vm.runInContext('historyFlights[0].profile_id',context),'dart');
  assert.equal(vm.runInContext('activeProfileId',context),'dart','Moving a flight must not change the selected plane');
  context.document.elementFromPoint = () => element('flight-drop-options').children[0];
  const nextGrip = element('history-list').children[0].children[4];
  nextGrip.pointerdown({button:0,pointerId:3,clientX:100,clientY:600,preventDefault(){}});
  nextGrip.pointermove({clientX:100,clientY:450});
  await nextGrip.pointerup({pointerId:3});
  assert.equal(profilePosts.at(-1).profile_id,null);
  const postsBeforeCancel = profilePosts.length;
  const cancelGrip = element('history-list').children[0].children[4];
  cancelGrip.pointerdown({button:0,pointerId:4,clientX:100,clientY:600,preventDefault(){}});
  cancelGrip.pointercancel();
  await cancelGrip.pointerup({pointerId:4});
  assert.equal(profilePosts.length,postsBeforeCancel,'Cancelled drag must not save');
  assert.equal(vm.runInContext('draggedFlightId',context),null);
  assert.equal(element('flight-drop-tray').hidden,true);
  element('planes-tab').click();
  assert.equal(element('planes-tab').attributes['aria-selected'],'true');
  assert.equal(element('flights-view').hidden,true);
  element('flights-tab').click();
  assert.equal(element('planes-view').hidden,true);
  element('compare-mode').click();
  assert.equal(element('clear-comparisons').hidden,false);
  assert.equal(element('history-list').children[0].children[2].children[0].hidden,false);
  element('compare-mode').click();
  assert.equal(element('clear-comparisons').hidden,true);
  assert.equal(element('history-list').children[0].children[2].children[0].hidden,true);
  element('plane-form').hidden=true;
  element('add-plane-toggle').click();
  assert.equal(element('plane-form').hidden,false);
  element('add-plane-toggle').click();
  assert.equal(element('plane-form').hidden,true);
  assert(!html.includes('id="plane-status"'),'Only one shared status area');
  const optionsMenu = element('history-list').children[0].children[3];
  optionsMenu.open = true; optionsMenu.toggle();
  const menuRows = element('history-list').children;
  vm.runInContext('renderHistory()', context);
  assert.equal(element('history-list').children, menuRows,'Polling must preserve an open actions menu');
  optionsMenu.keydown({key:'Escape'});
  assert.equal(vm.runInContext('openLogMenu',context),null);
  assert.equal(optionsMenu.open,false);
  vm.runInContext(`logStatus('Save failed',true,()=>{})`,context);
  assert.equal(element('history-status').attributes.role,'alert');
  assert.equal(element('log-retry').hidden,false);
  vm.runInContext(`logStatus('Saved.')`,context);
  assert.equal(element('log-retry').hidden,true);
  vm.runInContext(`historyFlights[0].video_status='ready';historyFlights[0].video_duration=1;latestData={session_id:'video-session'};renderHistory()`,context);
  const requestsBeforeVideo = requests;
  const graphBeforeVideo = element('observed-line').attributes.d;
  element('history-list').children[0].children[2].children[2].click();
  assert.equal(element('clip-dialog').open,true);
  assert(element('clip-video').src.includes('/api/video/video-session/saved-1.mp4'));
  assert.equal(element('observed-line').attributes.d,graphBeforeVideo,'Video must not alter live graph');
  assert.equal(requests,requestsBeforeVideo,'Video must not trigger paid narration');
  element('clip-close').click();
  assert.equal(element('clip-dialog').open,false);
  assert.equal(element('clip-video').src,undefined);
  assert.equal(element('clip-video').paused,true);
  vm.runInContext(`openVideo(historyFlights[0]);render({status:'READY',session_id:'new-session',voice:{}})`,context);
  assert.equal(element('clip-dialog').open,false,'Restart must close the old session recording');
  console.log('Video checks passed: local session URL, player cleanup, restart isolation, no graph or voice side effects.');
  console.log('Flight Log checks passed: tabs, contextual add form, compare mode and drag-only category tray.');
  console.log('Flight drag checks passed: categorizing, unassigning, polling protection and cancellation.');
  console.log('Profile checks passed: active plane, drag reorder, flight assignment, history filtering.');
  console.log('Coach checks passed: automatic, once per flight, mute stops, no replay.');
  console.log('Score checks passed: mismatched score rejected, late audio cancelled.');
  console.log('Graph checks passed: invalid samples, path breaks, real launch point, exit labels, reset.');
  console.log('History checks passed: cards, overlays, coordinate scaling, replay/scrub isolation, selection limit, clear.');
  console.log('Name editor checks passed: save, cancel, polling protection; collapse accessibility and reduced-motion support.');
})().catch(error => {console.error(error); process.exitCode = 1;});
