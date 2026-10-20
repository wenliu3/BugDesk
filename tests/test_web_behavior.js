/* Exercise async browser state transitions without contacting a browser or server. */
"use strict";
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const plain=value=>JSON.parse(JSON.stringify(value));
function element(){
  const value={textContent:'',value:'',checked:false,hidden:false,disabled:false,children:[],get childNodes(){return this.children;},dataset:{},scrollTop:0,className:'',listeners:{},attributes:{},
    setAttribute(key,item){this.attributes[key]=String(item);},addEventListener(type,callback){(this.listeners[type]||=[]).push(callback);},
    querySelectorAll(selector){const tags=selector.split(',');return this.children.flatMap(child=>[...(tags.includes(child.tagName)?[child]:[]),...child.querySelectorAll(selector)]);},querySelector(){return null;},
    replaceChildren(...children){this.children=children;children.forEach(child=>{child.parentElement=this;});this.scrollTop=0;},append(...children){this.children.push(...children);children.forEach(child=>{child.parentElement=this;});},prepend(...children){this.children.unshift(...children);children.forEach(child=>{child.parentElement=this;});},remove(){},focus(){},select(){},scrollIntoView(){},showModal(){this.open=true;},close(){this.open=false;(this.listeners.close||[]).forEach(callback=>callback({target:this}));},};
  value.classList={toggle(name,force){const tokens=new Set(value.className.split(/\s+/).filter(Boolean)),enabled=force===undefined?!tokens.has(name):!!force;if(enabled)tokens.add(name);else tokens.delete(name);value.className=[...tokens].join(' ');return enabled;}};
  return value;
}
function harness(file){
  const elements=new Map(),events={},timers=[],calls=[],toasts=[],requests=[];
  let context;
  const create=tag=>{const item=element();item.tagName=tag;let id='';Object.defineProperty(item,'id',{get(){return id;},set(next){id=next;elements.set(id,item);}});item.focus=()=>{context.document.activeElement=item;(item.listeners.focus||[]).forEach(callback=>callback({target:item}));for(let ancestor=item;ancestor;ancestor=ancestor.parentElement)(ancestor.listeners.focusin||[]).forEach(callback=>callback({target:item}));};return item;};
  const get=id=>{if(!elements.has(id))elements.set(id,create());return elements.get(id);};
  context={console,Map,Set,Date,URL,structuredClone,Promise,Array,Number,JSON,
    location:{origin:'http://127.0.0.1:12345'},
    setTimeout(callback){timers.push(callback);return timers.length;},clearTimeout(){},setInterval(){return 1;},clearInterval(){},
    document:{getElementById:get,createElement:create,body:element(),documentElement:{dataset:{}},cookie:'',querySelectorAll(){return [];},addEventListener(){},hidden:false},
    window:{addEventListener(type,callback){events[type]=callback;},dispatchEvent(event){events[event.type]?.(event);}},
    localStorage:{getItem:()=>null,setItem(){}},Event:class{constructor(type){this.type=type;}},
    $:get,node:(tag,className,content)=>{const item=create();item.tagName=tag;item.className=className||'';if(content!==undefined)item.textContent=content;return item;},icon:()=>element(),button:(text,className,action)=>{const item=create();item.className=className||'';item.textContent=text||'';if(action)item.addEventListener('click',action);return item;},
    toast:message=>toasts.push(message),errorMessage:error=>error.message,
    flushSave:async()=>{},replaceState:async state=>requests.push(state),
    api:async(route,data)=>{calls.push({route,data});return {};},
    state:{job:{running:false}},batchBusy:false,scanBusy:false,
  };
  vm.createContext(context);
  const source=fs.readFileSync(path.join(__dirname,'..','web',file),'utf8').replace(/\binit\(\);\s*$/,'');
  vm.runInContext(source,context,{filename:file});
  return {context,elements,events,timers,calls,toasts,requests,get,fire:(id,type,details={})=>{const item=typeof id==='string'?get(id):id;const event={target:item,defaultPrevented:false,preventDefault(){this.defaultPrevented=true;},...details};(item.listeners[type]||[]).forEach(callback=>callback(event));return event;},run:source=>vm.runInContext(source,context)};
}
function saveHarness(){
  const h=harness('app.js');
  h.run('renderChrome=()=>{};renderEditor=()=>{};bindEvents();state={settings:{},bugs:[{id:"a",title:"A",steps:"",actual:"",expected:""},{id:"b",title:"B",steps:"",actual:"",expected:""}]};currentId="a";');
  h.context.testSave=payload=>{const pending=deferred();h.calls.push({payload,...pending});return pending.promise;};
  h.run('api=async(path,payload)=>testSave(payload);');
  return h;
}
const appearanceSource=fs.readFileSync(path.join(__dirname,'..','web','app.js'),'utf8').match(/\/\* Appearance bootstrap[^\n]*\*\/([\s\S]*?)\/\* UI icons \*\//)[1];
function appearanceHarness({cookie='',stored=null,dark=false,blocked=false}={}){
  const events={},systemEvents={},writes=[],root={dataset:{}},system={matches:dark,addEventListener(type,callback){systemEvents[type]=callback;}};
  const document={documentElement:root};let savedCookie=cookie;
  Object.defineProperty(document,'cookie',{get(){if(blocked)throw new Error('blocked');return savedCookie;},set(value){if(blocked)throw new Error('blocked');savedCookie=value;}});
  const window={matchMedia:()=>system,addEventListener(type,callback){events[type]=callback;},dispatchEvent(event){events[event.type]?.(event);}};
  const localStorage={getItem(){if(blocked)throw new Error('blocked');return stored;},setItem(key,value){if(blocked)throw new Error('blocked');writes.push({key,value});}};
  vm.runInNewContext(appearanceSource,{document,window,localStorage,Event:class{constructor(type){this.type=type;}}});
  return {window,root,events,system,systemEvents,writes,cookie:()=>savedCookie};
}

test('appearance follows the system until a manual selection and retains that selection when the local port changes',()=>{
  const first=appearanceHarness({dark:true});assert.equal(first.root.dataset.theme,'dark');assert.equal(first.writes.length,0);
  first.window.bugDeskAppearance.toggle();assert.equal(first.root.dataset.theme,'light');
  assert.deepEqual(first.writes,[{key:'bugdesk.theme',value:'light'}]);assert.match(first.cookie(),/bugdesk_theme=light; Path=\//);
  first.system.matches=true;first.systemEvents.change();assert.equal(first.root.dataset.theme,'light');
  const restarted=appearanceHarness({cookie:first.cookie(),stored:null,dark:true});assert.equal(restarted.root.dataset.theme,'light');
});

test('appearance tolerates blocked or invalid browser storage and updates with the system before manual selection',()=>{
  const blocked=appearanceHarness({blocked:true,dark:true});assert.equal(blocked.root.dataset.theme,'dark');
  assert.doesNotThrow(()=>blocked.window.bugDeskAppearance.toggle());assert.equal(blocked.root.dataset.theme,'light');
  const fresh=appearanceHarness({cookie:'bugdesk_theme=invalid',stored:'invalid',dark:false});assert.equal(fresh.root.dataset.theme,'light');
  fresh.system.matches=true;fresh.systemEvents.change();assert.equal(fresh.root.dataset.theme,'dark');
  const saved=appearanceHarness({stored:'dark',dark:false});assert.equal(saved.root.dataset.theme,'dark');
  const newer=appearanceHarness({cookie:'other=value; bugdesk_theme=light',stored:'dark',dark:true});assert.equal(newer.root.dataset.theme,'light');
});

test('theme switching updates its accessible button without saving, changing review state or replacing draft input',()=>{
  const h=harness('app.js');h.context.document.documentElement={dataset:{}};h.context.document.cookie='';
  h.context.localStorage={getItem:()=>null,setItem(){}};h.context.Event=class{constructor(type){this.type=type;}};
  h.context.window.matchMedia=()=>({matches:false,addEventListener(){}});h.context.window.dispatchEvent=event=>h.events[event.type]?.(event);
  vm.runInContext(appearanceSource,h.context);
  h.run('installThemeToggle();state.bugs=[{id:"a",title:"正在编辑",reviewed:true}];currentId="a";dirtyBugs.set("a",{steps:"未保存的内容"});');
  const input=h.get('draftInput'),before=plain(h.run('({state,currentId,dirty:Array.from(dirtyBugs)})'));h.context.document.activeElement=input;
  assert.equal(h.get('themeToggle').attributes['aria-label'],'切换到深色模式');
  h.fire('themeToggle','click');assert.equal(h.context.document.documentElement.dataset.theme,'dark');
  assert.equal(h.get('themeToggle').attributes['aria-label'],'切换到浅色模式');assert.equal(h.context.document.activeElement,input);
  h.fire('themeToggle','click');assert.equal(h.context.document.documentElement.dataset.theme,'light');
  assert.deepEqual(plain(h.run('({state,currentId,dirty:Array.from(dirtyBugs)})')),before);assert.equal(h.calls.length,0);assert.equal(h.requests.length,0);
});
function savedState(steps){return {settings:{},bugs:[{id:'a',title:'A',steps,actual:'',expected:''},{id:'b',title:'B',steps:'',actual:'',expected:''}]};}

test('cancelling folder relinking keeps the current batch and never starts a scan',async()=>{
  const h=saveHarness(),before=plain(h.run('state'));
  h.get('folderInput').value='D:/synthetic-new-location';h.context.chooseScanRelinks=async path=>{assert.equal(path,'D:/synthetic-new-location');return null;};
  await h.run('scanFolder()');
  assert.deepEqual(plain(h.run('state')),before);assert.equal(h.calls.length,0);assert.equal(h.run('batchBusy'),false);
});

test('closing a tab is protected while an autosave request is in flight',async()=>{
  const h=saveHarness();
  const saving=h.run('dirtyBugs.set("a",{steps:"first edit"});flushSave();');
  await tick();
  assert.equal(h.run('dirtyBugs.size'),0);
  assert.equal(h.run('activeSaves'),1);
  assert.equal(h.get('saveStatus').textContent,'正在保存…');
  let prevented=false;
  h.events.beforeunload({preventDefault(){prevented=true;},returnValue:undefined});
  assert.equal(prevented,true);
  h.calls[0].resolve(savedState('first edit'));
  await saving;await h.run('saveChain');
  assert.equal(h.run('hasPendingSave()'),false);
  assert.equal(h.get('saveStatus').textContent,'已自动保存');
});

test('a failed save restores its older fields while keeping edits made during the request',async()=>{
  const h=saveHarness();
  const saving=h.run('dirtyBugs.set("a",{steps:"older",preconditions:"keep this"});flushSave();');
  await tick();
  h.run('localEdit(state.bugs[0],{steps:"newer",actual:"observed"});');
  assert.equal(h.get('saveStatus').textContent,'正在保存…');
  h.calls[0].reject(new Error('isolated disk failure'));
  await assert.rejects(saving,/isolated disk failure/);
  assert.equal(h.run('activeSaves'),0);
  assert.equal(h.run('hasPendingSave()'),true);
  assert.deepEqual(plain(h.run('dirtyBugs.get("a")')),{steps:'newer',preconditions:'keep this',actual:'observed',reviewed:false});
  assert.equal(h.get('saveStatus').textContent,'保存失败 · Ctrl+S 重试');
  const retry=h.run('flushSave()');await tick();
  assert.equal(h.calls[1].payload.bugs[0].steps,'newer');
  h.calls[1].resolve(savedState('newer'));await retry;
  assert.equal(h.run('hasPendingSave()'),false);
});

test('queued saves preserve later edits and keep the pending indicator until both finish',async()=>{
  const h=saveHarness();
  const first=h.run('dirtyBugs.set("a",{steps:"first"});flushSave();');await tick();
  const second=h.run('localEdit(state.bugs[0],{steps:"second"});flushSave();');
  h.calls[0].resolve(savedState('first'));await first;await tick();
  assert.equal(h.calls.length,2);
  assert.equal(h.calls[1].payload.bugs[0].steps,'second');
  assert.equal(h.run('state.bugs[0].steps'),'second');
  assert.equal(h.run('hasPendingSave()'),true);
  assert.equal(h.get('saveStatus').textContent,'正在保存…');
  h.calls[1].resolve(savedState('second'));await second;
  assert.equal(h.run('state.bugs[0].steps'),'second');
  assert.equal(h.run('hasPendingSave()'),false);
});

test('switching to another draft still waits for the current draft save',async()=>{
  const h=saveHarness();
  const switching=h.run('dirtyBugs.set("a",{steps:"save before switch"});selectBug("b");');
  await tick();assert.equal(h.run('currentId'),'a');assert.equal(h.run('activeSaves'),1);
  h.calls[0].resolve(savedState('save before switch'));await switching;
  assert.equal(h.run('currentId'),'b');assert.equal(h.run('hasPendingSave()'),false);
});

test('redrawing the main Bug list keeps its independent scroll position',()=>{
  const h=saveHarness();h.get('bugList').scrollTop=173;
  h.run('renderList()');assert.equal(h.get('bugList').children.length,2);
  assert.equal(h.get('bugList').scrollTop,173);
});

test('editor navigation follows search results and disables both controls when the current Bug is filtered out',()=>{
  const h=saveHarness();
  h.run('state.bugs=[{id:"a",title:"match A"},{id:"b",title:"other"},{id:"c",title:"match C"}];search="match";currentId="a";refreshEditorNavigation();');
  assert.equal(h.get('previousBugButton').disabled,true);
  assert.equal(h.get('nextBugButton').disabled,false);
  h.run('currentId="c";refreshEditorNavigation();');
  assert.equal(h.get('previousBugButton').disabled,false);
  assert.equal(h.get('nextBugButton').disabled,true);
  h.run('currentId="b";refreshEditorNavigation();');
  assert.equal(h.get('previousBugButton').disabled,true);
  assert.equal(h.get('nextBugButton').disabled,true);
});

test('header popovers close without changing drafts and can preserve the panel being opened',()=>{
  const h=saveHarness();
  h.get('folderPicker').open=true;h.get('moreMenu').open=true;
  const before=plain(h.run('state'));
  h.run('closeHeaderPanels($("folderPicker"));');
  assert.equal(h.get('folderPicker').open,true);
  assert.equal(h.get('moreMenu').open,false);
  h.run('closeHeaderPanels();');
  assert.equal(h.get('folderPicker').open,false);
  assert.deepEqual(plain(h.run('state')),before);
  assert.equal(h.calls.length,0);
});

test('per-Bug settings count the five fields once each and update without replacing active inputs',()=>{
  const h=saveHarness();
  h.run('state.bugs[0].overrides={type:"interface",severity:"2",pri:"1",assignedTo:"tester",assignee_name:"测试员",probability:"低",os:"Windows"};');
  assert.equal(h.run('bugOverrideCount(state.bugs[0])'),5);
  const summary=h.get('bugSettingsSummary'),status=h.get('bugSettingsStatus');
  h.run('refreshBugSettings(state.bugs[0]);');
  assert.equal(status.textContent,'已修改 5 项');assert.equal(h.get('bugSettingsReset').disabled,false);
  assert.match(summary.className,/has-overrides/);
  h.run('state.bugs[0].overrides={assignee_name:"测试员",type:"",probability:"  ",os:"Windows"};refreshBugSettings(state.bugs[0]);');
  assert.equal(status.textContent,'跟随公共配置');assert.equal(h.get('bugSettingsReset').disabled,true);
  assert.equal(h.get('bugSettingsSummary'),summary);assert.equal(h.get('bugSettingsStatus'),status);
});

test('restoring public settings clears only this Bug\'s five overrides and invalidates its review',()=>{
  const h=saveHarness();
  h.run('state.settings={pri:"4",assignedTo:"shared",probability:"中"};state.bugs[0].reviewed=true;state.bugs[0].overrides={type:"interface",severity:"2",pri:"1",assignedTo:"tester",assignee_name:"测试员",probability:"低",os:"Windows"};state.bugs[1].overrides={pri:"2"};');
  const shared=plain(h.run('state.settings')),other=plain(h.run('state.bugs[1]'));
  assert.equal(h.run('resetBugOverrides(state.bugs[0])'),true);
  assert.deepEqual(plain(h.run('state.bugs[0].overrides')),{os:'Windows'});
  assert.equal(h.run('state.bugs[0].reviewed'),false);
  assert.equal(h.run('effectiveSettings(state.bugs[0]).pri'),'4');
  assert.equal(h.run('effectiveSettings(state.bugs[0]).assignedTo'),'shared');
  assert.equal(h.run('effectiveSettings(state.bugs[0]).probability'),'中');
  assert.deepEqual(plain(h.run('state.settings')),shared);assert.deepEqual(plain(h.run('state.bugs[1]')),other);
  assert.deepEqual(plain(h.run('Array.from(dirtyBugs)')),[['a',{overrides:{os:'Windows'},reviewed:false}]]);
  assert.equal(h.run('resetBugOverrides(state.bugs[0])'),false);
});

test('locked Bugs cannot restore or change their individual settings',()=>{
  for(const lock of ['state.bugs[0].status="submitted"','state.bugs[0].remote_id="123"','batchBusy=true','state.job={running:true}']){
    const h=saveHarness();h.run('state.bugs[0].overrides={pri:"1"};'+lock);
    const before=plain(h.run('state'));
    assert.equal(h.run('resetBugOverrides(state.bugs[0])'),false);
    h.run('const fields=node("div");renderBugOverrideFields(fields,state.bugs[0],true);');
    const priority=h.run('fields.children[2].children[1]');priority.value='2';h.fire(priority,'change');
    assert.equal(priority.disabled,true);assert.deepEqual(plain(h.run('state')),before);assert.equal(h.run('dirtyBugs.size'),0);
  }
});

test('the probability override displays its saved value and returns to public configuration when cleared',()=>{
  const h=saveHarness();h.run('state.bugs[0].overrides={};const probability=probabilityOverrideField(state.bugs[0],false).children[1];');
  const select=h.run('probability');assert.equal(select.value,'');
  select.value='低';h.fire(select,'change');
  assert.equal(h.run('state.bugs[0].overrides.probability'),'低');assert.equal(h.run('bugOverrideCount(state.bugs[0])'),1);
  h.run('const restored=probabilityOverrideField(state.bugs[0],false).children[1];');
  assert.equal(h.run('restored.value'),'低');
  select.value='';h.fire(select,'change');
  assert.equal(h.run('bugOverrideCount(state.bugs[0])'),0);assert.equal(h.run('"probability" in state.bugs[0].overrides'),false);
});

test('the main header opens the graphical WorkBuddy guide without connecting, saving or changing drafts',()=>{
  const h=saveHarness(),effects=[];
  h.run('state.connection={connected:false};state.bugs[0].actual="尚未保存的实际现象";dirtyBugs.set("a",{actual:"尚未保存的实际现象"});editorTab="description";');
  h.context.workBuddyStatus={enabled:false,pending:null};
  h.context.workBuddyAssignments=new Map([['a',{rowId:'retained-source',checked:false}]]);
  h.context.workBuddyOpenHelp=()=>effects.push('guide');
  h.context.openWorkBuddy=()=>effects.push('organize');h.context.flushSave=()=>effects.push('save');
  const before=plain(h.run('({state,currentId,editorTab,dirty:Array.from(dirtyBugs)})'));
  const assignments=plain(Array.from(h.context.workBuddyAssignments));
  h.fire('workBuddyGuideButton','click');
  assert.deepEqual(effects,['guide']);assert.equal(h.calls.length,0);assert.equal(h.requests.length,0);
  assert.deepEqual(plain(h.run('({state,currentId,editorTab,dirty:Array.from(dirtyBugs)})')),before);
  assert.deepEqual(h.context.workBuddyStatus,{enabled:false,pending:null});
  assert.deepEqual(plain(Array.from(h.context.workBuddyAssignments)),assignments);
});

function buddyHarness(){
  const h=harness('workbuddy.js');
  h.context.testRendered=()=>{h.rendered=(h.rendered||0)+1;};
  h.run('workBuddyDialog={open:true,setAttribute(){},querySelectorAll(){return [];}};workBuddyRenderPlan=()=>testRendered();');
  return h;
}
function plan(id,rows,bugs=[{id:'a'},{id:'b'},{id:'c'}]){return {plan_id:id,review_scope:'bugs',rows,bugs};}

test('partial WorkBuddy imports retain remaining Bug choices and reusable source rows',async()=>{
  const h=buddyHarness();
  const rows=[{row_id:'r1',suggested_bug_id:'a',match_type:'exact_id'},{row_id:'r2',suggested_bug_id:'b',match_type:'exact_id'},{row_id:'r3',match_type:'unmatched'}];
  h.context.original=plan('old',rows);
  h.context.remaining={...plan('new',rows,[{id:'b'},{id:'c'}]),total_bugs:3,completed_bug_ids:['a']};
  h.run('workBuddyPlan=original;workBuddyStatus={enabled:true,pending:original};workBuddyInitializePlan();workBuddyAssignments.set("b",{checked:false,rowId:"r1"});workBuddyAssignments.set("c",{checked:false,rowId:""});workBuddyReplaceContent=true;');
  h.context.api=async(route,data)=>{h.calls.push({route,data});return {state:{bugs:[]},applied:1,unchanged:0,skipped_fields:2,remaining_bugs:2,pending:h.context.remaining};};
  await h.run('workBuddyApply()');
  assert.deepEqual(plain(h.calls[0].data),{plan_id:'old',review_scope:'bugs',assignments:[{row_id:'r1',bug_id:'a',mode:'replace'}]});
  assert.equal(h.run('workBuddyPlan.plan_id'),'new');
  assert.equal(h.run('workBuddyStatus.pending.plan_id'),'new');
  assert.equal(h.run('workBuddyAssignments.has("a")'),false);
  assert.deepEqual(plain(h.run('workBuddyAssignments.get("b")')),{checked:false,rowId:'r1'});
  assert.deepEqual(plain(h.run('workBuddyAssignments.get("c")')),{checked:false,rowId:''});
  assert.equal(h.run('workBuddyPlan.rows.length'),3);
  assert.equal(h.run('workBuddyRow(workBuddyBugs()[0]).row_id'),'r1');
  assert.equal(h.run('workBuddyReplaceContent'),true);
  assert.match(h.toasts[0],/已导入 1 个 Bug，剩余 2 个 Bug 待整理/);
  assert.match(h.toasts[0],/保留了 2 项已有内容/);
  assert.equal(h.get('workBuddyApply').disabled,true);
});

test('consuming the final WorkBuddy Bug clears the pending plan',async()=>{
  const h=buddyHarness();h.context.original=plan('last',[{row_id:'r1',suggested_bug_id:'a',match_type:'exact_id'}],[{id:'a'}]);
  h.run('workBuddyPlan=original;workBuddyStatus={enabled:true,pending:original};workBuddyInitializePlan();');
  h.context.api=async()=>({state:{bugs:[]},applied:1,remaining_bugs:0,pending:null});
  await h.run('workBuddyApply()');
  assert.equal(h.run('workBuddyPlan'),null);assert.equal(h.run('workBuddyStatus.pending'),null);
  assert.equal(h.run('workBuddyAssignments.size'),0);assert.match(h.toasts[0],/剩余 0 个 Bug 待整理/);
});

test('lightweight polling keeps the full plan and Bug choices without rendering empty cards',async()=>{
  const h=buddyHarness();h.context.original=plan('known id',[{row_id:'r1',suggested_bug_id:'a',match_type:'exact_id'}]);
  h.run('workBuddyPlan=original;workBuddyStatus={enabled:true,pending:original};workBuddyInitializePlan();workBuddyAssignments.set("c",{checked:false,rowId:"r1"});');
  h.context.api=async route=>{h.calls.push({route});return {enabled:true,pending:{plan_id:'known id',unchanged:true}};};
  await h.run('workBuddyPoll()');
  assert.equal(h.calls[0].route,'/api/workbuddy/status?known_plan_id=known%20id');
  assert.equal(h.run('workBuddyStatus.pending===original'),true);
  assert.equal(h.run('workBuddyStatus.pending.rows.length'),1);
  assert.deepEqual(plain(h.run('workBuddyAssignments.get("c")')),{checked:false,rowId:'r1'});
  assert.equal(h.rendered||0,0);
});

test('a lightweight marker without a matching full cache causes one full reload',async()=>{
  const h=buddyHarness();h.context.original=plan('cache',[{row_id:'r1',suggested_bug_id:'a',match_type:'exact_id'}]);
  h.run('workBuddyStatus={enabled:true,pending:{plan_id:"cache"}};');
  h.context.api=async route=>{h.calls.push({route});return h.calls.length===1?{enabled:true,pending:{plan_id:'cache',unchanged:true}}:{enabled:true,pending:h.context.original};};
  await h.run('workBuddyPoll()');
  assert.deepEqual(h.calls.map(call=>call.route),['/api/workbuddy/status?known_plan_id=cache','/api/workbuddy/status']);
  assert.equal(h.run('workBuddyPlan.rows.length'),1);assert.equal(h.rendered,1);
});

function textOf(item){return String(item.textContent||'')+(item.children||[]).map(textOf).join(' ');}
function byClass(item,className){return (item.children||[]).flatMap(child=>[...(String(child.className||'').split(/\s+/).includes(className)?[child]:[]),...byClass(child,className)]);}
function buddyViewHarness(change=()=>{}){
  const h=harness('workbuddy.js');
  h.context.original={plan_id:'view',review_scope:'bugs',bugs:[
    {id:'a',title:'PD1-CA1_短标题',original_title:'10月17日_消息订阅失败截图'},
    {id:'b',title:'完整长标题：'+('语音播放后跳回上一界面，核对具体操作与结果。'.repeat(10))},
    {id:'c',title:'另一条待核对的 Bug'},
  ],rows:[
    {row_id:'r1',case_id:'PD1-CA1',title:'完整 ID 匹配',suggested_bug_id:'a',match_type:'exact_id',steps:'1.打开页面\n2.执行操作',expected:'预期结果',actual:'实际现象'},
    {row_id:'r2',case_id:'PD1-CA2',title:'AI 匹配建议',suggested_bug_id:'b',match_type:'suggested',steps:'操作二',expected:'预期二',actual:'现象二'},
    {row_id:'r3',case_id:'PD1-CA3',title:'尚未关联的用例',suggested_bug_id:'',match_type:'unmatched',steps:'操作三',expected:'预期三',actual:'现象三'},
  ]};
  change(h.context.original);
  h.run('installWorkBuddy();workBuddyDialog.open=true;workBuddyPlan=original;workBuddyStatus={enabled:true,pending:original};workBuddyInitializePlan();workBuddyRenderPlan();');
  return h;
}

test('one AI-combined proposal previews every original scenario and imports as one Bug',async()=>{
  const h=buddyViewHarness(value=>{
    value.rows[0]={row_id:'combined',case_id:'',title:'设备卡片的两个入口文案异常',suggested_bug_id:'a',match_type:'suggested',
      preconditions:'已绑定设备',steps:'场景一：查看直播入口\n场景二：查看回看入口',actual:'两个入口的文案均与需求不符',expected:'场景一：看直播\n场景二：看回看',
      source_cases:[
        {case_id:'CASE-LIVE',title:'直播入口文案',steps:'进入家居页查看直播入口',actual:'直播入口文案异常',expected:'看直播'},
        {case_id:'CASE-REPLAY',title:'回看入口文案',steps:'进入家居页查看回看入口',actual:'回看入口文案异常',expected:'看回看'},
      ]};
  });
  assert.deepEqual(plain(h.run('workBuddyAssignments.get("a")')),{rowId:'combined',checked:false});
  assert.match(textOf(h.get('workBuddyHoverPreview')),/已合并 2 条用例/);
  assert.match(textOf(h.get('workBuddyHoverPreview')),/场景一：查看直播入口\n场景二：查看回看入口/);
  const originals=textOf(h.get('workBuddySourceCases'));
  assert.match(originals,/CASE-LIVE/);assert.match(originals,/CASE-REPLAY/);
  assert.match(originals,/进入家居页查看直播入口/);assert.match(originals,/进入家居页查看回看入口/);
  assert.match(h.get('workBuddySummary').title,/收到 4 条用例 · 3 份整理建议/);
  assert.match(textOf(h.get('workBuddyBugs')),/已合并 2 条用例/);
  h.get('workBuddyCaseSearch').value='CASE-REPLAY';h.fire('workBuddyCaseSearch','input');
  assert.deepEqual(h.get('workBuddyCaseOptions').children.map(item=>item.dataset.rowId),['combined']);
  assert.equal(h.get('workBuddyCaseOptions').children[0].children[0].checked,true);
  h.get('workBuddyDetailCheck').checked=true;h.fire('workBuddyDetailCheck','change');
  h.context.api=async(route,data)=>{h.calls.push({route,data});return {state:{bugs:[]},applied:1,remaining_bugs:0,pending:null};};
  await h.run('workBuddyApply()');
  assert.deepEqual(plain(h.calls[0]),{route:'/api/workbuddy/apply',data:{plan_id:'view',review_scope:'bugs',assignments:[{row_id:'combined',bug_id:'a',mode:'fill'}]}});
});

test('a combined report can be found by a secondary source ID or its original query',()=>{
  const h=buddyViewHarness(value=>{
    value.rows[1].source_cases=[{case_id:'CASE-ONE',title:'第一条来源'},{case_id:'CASE-TWO',title:'第二条来源',steps:'query:播放指定的测试故事'}];
  });
  assert.deepEqual(plain(h.run('workBuddyCandidateRows(workBuddyBugs()[1],"指定的测试故事").map(row=>row.row_id)')),['r2']);
  h.get('workBuddySearch').value='CASE-TWO';h.fire('workBuddySearch','input');
  assert.equal(h.run('workBuddyCurrentBugId'),'b');
  assert.deepEqual(h.get('workBuddyBugs').children.map(item=>item.dataset.bugId),['b']);
  assert.match(textOf(h.get('workBuddySourceCases')),/CASE-TWO/);
  assert.deepEqual(plain(h.run('workBuddyAssignments.get("b")')),{rowId:'r2',checked:false});
});

test('an existing draft clearly explains how to import a combined report with new scenarios',()=>{
  const h=buddyViewHarness(value=>{
    value.bugs[0].steps='只包含原来的场景';
    value.rows[0].source_cases=[{case_id:'CASE-ONE'},{case_id:'CASE-TWO'}];
    value.rows[0].steps='场景一：原来的操作\n场景二：新增操作';
  });
  assert.match(textOf(h.get('workBuddyHoverPreview')),/合并报告与已有内容不同/);
  assert.match(textOf(h.get('workBuddyHoverPreview')),/覆盖已有内容/);
  assert.equal(h.get('workBuddyReplace').checked,false);
});

test('saved multi-case Bugs remain searchable and show all source identities in review context',()=>{
  const h=harness('app.js');
  h.run('state={settings:{},bugs:[{id:"a",title:"一份已合并报告",steps:"场景一、场景二",actual:"共同现象",expected:"分别符合需求",case_source:{case_id:"CASE-ONE"},case_sources:[{case_id:"CASE-ONE",case_title:"入口一"},{case_id:"CASE-TWO",case_title:"入口二",tester:"测试人员乙"}]}]};search="case-two";');
  assert.deepEqual(plain(h.run('shownBugs().map(bug=>bug.id)')),['a']);
  const context=h.run('reportContext(state.bugs[0])');assert.match(textOf(context),/CASE-ONE、CASE-TWO/);
  h.run('search="测试人员乙"');assert.equal(h.run('shownBugs().length'),1);
  h.run('state.bugs[0].case_sources=[];search="case-one"');assert.equal(h.run('shownBugs().length'),1);
});

test('the before-after comparison follows fill and replace rules and never treats empty suggestions as deletions',()=>{
  const h=buddyViewHarness(value=>{value.bugs[0].steps='公共操作\n旧输入';value.bugs[0].actual='人工实际结果';value.rows[0].steps='公共操作\n新输入';value.rows[0].actual='';});
  let changes=plain(h.run('workBuddyImportChanges(workBuddyBug(),workBuddyRow())'));
  assert.equal(changes.find(change=>change.label==='复现步骤').retained,true);
  assert.equal(changes.find(change=>change.label==='复现步骤').after,'公共操作\n旧输入');assert.ok(!changes.some(change=>change.label==='实际结果'));
  assert.match(textOf(h.get('workBuddyComparison')),/当前模式不写入/);
  h.get('workBuddyReplace').checked=true;h.fire('workBuddyReplace','change');
  changes=plain(h.run('workBuddyImportChanges(workBuddyBug(),workBuddyRow())'));
  assert.equal(changes.find(change=>change.label==='复现步骤').after,'公共操作\n新输入');assert.equal(changes.find(change=>change.label==='复现步骤').replaces,true);
  assert.equal(h.get('workBuddyComparison').open,true);
  const highlights=h.get('workBuddyComparison').querySelectorAll('mark').map(textOf).join(' ');assert.match(highlights,/新输入/);assert.doesNotMatch(highlights,/公共操作/);
  assert.match(h.get('workBuddyComparison').querySelectorAll('del').map(textOf).join(' '),/旧输入/);
});

test('overwriting reviewed Bug facts requires the complete comparison confirmation and cancellation writes nothing',async()=>{
  const h=buddyViewHarness(value=>{value.bugs[0].steps='原草稿步骤';});
  h.get('workBuddyReplace').checked=true;h.fire('workBuddyReplace','change');
  let importing=h.run('workBuddyApply()');await tick();
  assert.equal(h.calls.length,0);assert.equal(h.get('workBuddyCompareDialog').open,true);
  assert.match(textOf(h.get('workBuddyCompareDialog')),/原草稿步骤/);assert.match(textOf(h.get('workBuddyCompareDialog')),/导入后/);
  h.fire(byClass(h.get('workBuddyCompareDialog'),'modal-footer')[0].children[0],'click');await importing;
  assert.equal(h.calls.length,0);assert.equal(h.run('workBuddyBusy'),false);assert.equal(h.run('workBuddyAssignments.get("a").checked'),true);
  h.context.api=async(route,data)=>{h.calls.push({route,data});return {state:{bugs:[]},applied:1,remaining_bugs:0,pending:null,undo:{transaction_id:'tx-one',count:1,titles:['A'],available:true,reason:''}};};
  importing=h.run('workBuddyApply()');await tick();h.fire(byClass(h.get('workBuddyCompareDialog'),'modal-footer')[0].children[1],'click');await importing;
  assert.equal(h.calls.length,1);assert.equal(h.calls[0].data.assignments[0].mode,'replace');assert.equal(h.get('workBuddyUndo').hidden,false);assert.equal(h.get('workBuddyUndo').disabled,false);
});

test('the latest import can be undone without an active WorkBuddy connection and clears the old pending preview',async()=>{
  const h=buddyViewHarness(),order=[];
  h.context.record={transaction_id:'last-import',count:2,titles:['A','B'],available:true,reason:''};
  h.run('workBuddyStatus.enabled=false;workBuddyStatus.undo=record;workBuddyRenderStatus()');
  assert.equal(h.get('workBuddyUndo').disabled,false);
  h.context.confirm=()=>false;await h.run('workBuddyUndoImport()');assert.equal(h.calls.length,0);
  h.context.confirm=()=>true;h.context.flushSave=async()=>order.push('save');
  h.context.api=async(route,data)=>{order.push('undo');h.calls.push({route,data});return {state:{bugs:[]},undone:2,pending:null,undo:null};};
  await h.run('workBuddyUndoImport()');
  assert.deepEqual(order,['save','undo']);assert.deepEqual(plain(h.calls[0]),{route:'/api/workbuddy/undo',data:{transaction_id:'last-import'}});
  assert.equal(h.run('workBuddyPlan'),null);assert.equal(h.run('workBuddyAssignments.size'),0);assert.equal(h.get('workBuddyUndo').hidden,true);
});

test('a stale undo record remains disabled and cannot send a restore request',async()=>{
  const h=buddyViewHarness();h.run('workBuddyStatus.undo={transaction_id:"old",count:1,available:false,reason:"草稿已修改"};workBuddyRenderStatus()');
  assert.equal(h.get('workBuddyUndo').disabled,true);assert.equal(h.get('workBuddyUndo').title,'草稿已修改');
  await h.run('workBuddyUndoImport()');assert.equal(h.calls.length,0);
});

test('clipboard failure expands the complete task before opening graphical help and selects it without changing review state',async()=>{
  const h=buddyViewHarness(),task=h.get('workBuddyTaskText'),area=h.get('workBuddyTaskArea'),search=h.get('workBuddyCaseSearch'),sheet=h.get('workBuddyHoverPreview'),options=h.get('workBuddyCaseOptions');
  h.run('workBuddyStatus.connection_file="D:/BugDesk/workbuddy-connection.json"');
  const expected=h.run('workBuddyTask()'),assignments=plain(h.run('Array.from(workBuddyAssignments)')),order=[],written=[];
  search.value='保留正在输入的查询';sheet.scrollTop=129;search.focus();
  h.context.navigator={clipboard:{async writeText(value){written.push(value);throw new Error('Clipboard unavailable');}}};
  h.context.openWorkBuddyGuide=()=>{order.push('guide');assert.equal(area.hidden,false);assert.equal(task.value,expected);};
  const focus=task.focus;task.focus=()=>{order.push('focus');focus();};task.select=()=>order.push('select');
  await h.run('workBuddyCopyTask()');
  assert.deepEqual(written,[expected]);assert.deepEqual(order,['guide','focus','select']);
  assert.equal(task.value,expected);assert.match(task.value,/D:\/BugDesk\/workbuddy-connection\.json/);assert.ok(task.value.endsWith('下面是复制的失败用例：\n'));
  assert.equal(h.context.document.activeElement,task);assert.equal(area.hidden,false);
  assert.deepEqual(plain(h.run('Array.from(workBuddyAssignments)')),assignments);assert.equal(h.run('workBuddyCurrentBugId'),'a');
  assert.equal(h.get('workBuddyCaseSearch'),search);assert.equal(search.value,'保留正在输入的查询');assert.equal(h.get('workBuddyHoverPreview'),sheet);assert.equal(sheet.scrollTop,129);assert.equal(h.get('workBuddyCaseOptions'),options);
});

test('successful task copying leaves graphical help closed and preserves the active review view',async()=>{
  const h=buddyViewHarness(),task=h.get('workBuddyTaskText'),search=h.get('workBuddyCaseSearch'),sheet=h.get('workBuddyHoverPreview'),options=h.get('workBuddyCaseOptions');
  h.run('workBuddyStatus.connection_file="D:/BugDesk/workbuddy-connection.json"');
  const expected=h.run('workBuddyTask()'),assignments=plain(h.run('Array.from(workBuddyAssignments)')),written=[];
  let guides=0,selections=0;h.context.openWorkBuddyGuide=()=>{guides++;};task.select=()=>{selections++;};
  h.context.navigator={clipboard:{async writeText(value){written.push(value);}}};
  search.value='保留当前筛选';search.focus();sheet.scrollTop=91;
  await h.run('workBuddyCopyTask()');
  assert.deepEqual(written,[expected]);assert.equal(task.value,expected);assert.equal(guides,0);assert.equal(selections,0);assert.equal(h.get('workBuddyTaskArea').hidden,true);
  assert.equal(h.context.document.activeElement,search);assert.equal(search.value,'保留当前筛选');assert.equal(h.get('workBuddyHoverPreview'),sheet);assert.equal(sheet.scrollTop,91);assert.equal(h.get('workBuddyCaseOptions'),options);
  assert.deepEqual(plain(h.run('Array.from(workBuddyAssignments)')),assignments);assert.equal(h.run('workBuddyCurrentBugId'),'a');
});

test('Bug-led review keeps exact and AI confirmation distinct and previews source facts',()=>{
  const h=buddyViewHarness();
  assert.equal(h.get('workBuddyBugs').children.length,3);
  assert.equal(byClass(h.get('workBuddyDetail'),'workbuddy-candidates-panel').length,1);
  assert.equal(byClass(h.get('workBuddyDetail'),'workbuddy-hover-preview').length,1);
  assert.equal(byClass(h.get('workBuddyDetail'),'workbuddy-fact').length,4);
  assert.equal(h.get('workBuddyHoverPreview').hidden,false);
  assert.equal(h.get('workBuddyHoverPreview').dataset.rowId,'r1');
  for(const obsolete of ['workBuddyCasePicker','workBuddyPickerToggle','workBuddyCasePreview','workBuddyDetailScroll'])assert.equal(h.elements.has(obsolete),false,obsolete);
  assert.deepEqual(plain(h.run('workBuddyAssignments.get("a")')),{rowId:'r1',checked:true});
  assert.deepEqual(plain(h.run('workBuddyAssignments.get("b")')),{rowId:'r2',checked:false});
  assert.deepEqual(plain(h.run('workBuddyAssignments.get("c")')),{rowId:'',checked:false});
  const summary=textOf(h.get('workBuddySummary'));
  for(const value of ['本批次 3 个 Bug','待匹配 1 个','已核对 1 个'])assert.ok(summary.includes(value),summary);
  assert.doesNotMatch(summary,/已匹配|收到.*用例/);
  assert.match(h.get('workBuddySummary').title,/已匹配 2 个 Bug · 收到 3 条用例/);
  assert.match(textOf(h.get('workBuddyApply')),/导入已核对 Bug（1）/);
  assert.equal(byClass(h.get('workBuddyHoverPreview'),'workbuddy-fact')[1].children[1].textContent,'1.打开页面\n2.执行操作');
  assert.match(textOf(h.get('workBuddyDetail')),/附件文件夹：10月17日_消息订阅失败截图/);
  assert.equal(h.elements.has('workBuddyTargetSelect'),false);
});

test('review keeps the source facts visible and commentary folded while preserving exact Bug titles',()=>{
  const h=buddyViewHarness(value=>{
    value.bugs[0].title='【厂商差异】【1.0需求版本】【消息订阅】删除任务后重新出现';
    value.rows[0].actual='删除任务后，列表重新出现原任务。';
    value.rows[0].source_actual='【厂商差异】【1.0需求版本】删除修改过的任务，又出来了';
    value.rows[0].review_notes=['需确认修改过程。'];
  });
  assert.ok(!h.get('workBuddyEvidence').open);
  const facts=byClass(h.get('workBuddyHoverPreview'),'workbuddy-fact').map(textOf).join(' ');
  assert.match(facts,/删除任务后，列表重新出现原任务/);
  assert.doesNotMatch(facts,/需确认修改过程|厂商差异/);
  assert.match(textOf(h.get('workBuddyReviewNotes')),/需确认修改过程/);
  assert.ok(!h.get('workBuddyReviewNotes').open);
  assert.match(textOf(h.get('workBuddyEvidence')),/删除修改过的任务，又出来了/);
  const fullTitle='【厂商差异】【1.0需求版本】【消息订阅】删除任务后重新出现';
  assert.equal(h.run('workBuddyTitleParts(workBuddyBug()).title'),fullTitle);
  assert.equal(byClass(h.get('workBuddyBugs'),'workbuddy-case-title')[0].textContent,fullTitle);
  assert.equal(byClass(h.get('workBuddyDetail'),'workbuddy-detail-heading')[0].children[1].textContent,fullTitle);
  assert.equal(h.run('workBuddyBug().title'),fullTitle);
  assert.equal(h.run('workBuddyTitleParts({title:"【设备离线】提示不消失"}).title'),'【设备离线】提示不消失');
  h.get('workBuddyHoverPreview').scrollTop=350;
  h.run('workBuddyChooseRow("r3")');
  assert.equal(h.get('workBuddyHoverPreview').scrollTop,0);
  assert.equal(h.get('workBuddyHoverPreview').dataset.rowId,'r3');
  h.run('workBuddyChooseRow("")');
  assert.equal(h.get('workBuddyHoverPreview').hidden,false);
  assert.equal(h.get('workBuddyHoverPreview').dataset.rowId,'');
  assert.match(textOf(h.get('workBuddyHoverPreview')),/尚未选择用例/);
});

test('hovering source candidates previews all four facts without changing the selected source or confirmation',()=>{
  const h=buddyViewHarness(value=>{value.rows[2].preconditions='候选三的前置条件';});
  const original=plain(h.run('Array.from(workBuddyAssignments)'));
  const selected=h.get('workBuddyCaseOptions').children.find(item=>item.dataset.rowId==='r1').children[0];
  const candidate=h.get('workBuddyCaseOptions').children.find(item=>item.dataset.rowId==='r3');
  h.fire(candidate,'pointerenter');
  assert.equal(h.get('workBuddyHoverPreview').hidden,false);
  assert.equal(h.get('workBuddyHoverPreview').dataset.rowId,'r1');
  h.timers.at(-1)();
  const hover=h.get('workBuddyHoverPreview');
  assert.equal(hover.hidden,false);assert.equal(hover.dataset.rowId,'r3');
  assert.deepEqual(byClass(hover,'workbuddy-fact').map(item=>item.children[1].textContent),['候选三的前置条件','操作三','现象三','预期三']);
  assert.match(textOf(hover),/尚未选用/);
  assert.deepEqual(plain(h.run('Array.from(workBuddyAssignments)')),original);
  assert.equal(h.get('workBuddyDetailCheck').checked,true);
  assert.equal(selected.checked,true);
  const nextCandidate=h.get('workBuddyCaseOptions').children.find(item=>item.dataset.rowId==='r2');
  h.fire(nextCandidate,'pointerenter');
  assert.equal(hover.hidden,false);
  assert.equal(hover.dataset.rowId,'r3');
  assert.match(textOf(hover),/候选三的前置条件/);
  h.timers.at(-1)();
  assert.equal(hover.hidden,false);assert.equal(hover.dataset.rowId,'r2');
  assert.deepEqual(byClass(hover,'workbuddy-fact').map(item=>item.children[1].textContent),['未提供','操作二','现象二','预期二']);
  assert.deepEqual(plain(h.run('Array.from(workBuddyAssignments)')),original);
  assert.equal(selected.checked,true);
  h.fire('workBuddyPickerLayer','pointerleave');
  assert.equal(hover.hidden,false);assert.equal(hover.dataset.rowId,'r1');
  assert.deepEqual(byClass(hover,'workbuddy-fact').map(item=>item.children[1].textContent),['未提供','1.打开页面\n2.执行操作','实际现象','预期结果']);
  assert.deepEqual(plain(h.run('Array.from(workBuddyAssignments)')),original);
});

test('the displayed candidate remains highlighted when the pointer moves into its source sheet',()=>{
  const h=buddyViewHarness(),sheet=h.get('workBuddyHoverPreview'),options=h.get('workBuddyCaseOptions');
  const original=plain(h.run('Array.from(workBuddyAssignments)'));
  const row=id=>options.children.find(item=>item.dataset.rowId===id);
  const shown=()=>options.children.filter(item=>item.className.split(/\s+/).includes('is-preview')).map(item=>item.dataset.rowId);
  assert.deepEqual(shown(),['r1']);
  h.fire(row('r3'),'pointerenter');
  assert.deepEqual(shown(),['r1']);
  h.timers.at(-1)();
  assert.equal(sheet.dataset.rowId,'r3');assert.deepEqual(shown(),['r3']);
  assert.equal(row('r3').attributes['aria-current'],'true');assert.equal(row('r1').attributes['aria-current'],'false');
  assert.equal(row('r1').children[0].checked,true);assert.equal(row('r3').children[0].checked,false);
  assert.ok(row('r1').className.split(/\s+/).includes('selected'));assert.ok(!row('r3').className.split(/\s+/).includes('selected'));
  h.fire(row('r3'),'pointerleave');h.fire(sheet,'pointerenter');h.run('workBuddyUpdateFooter()');
  assert.equal(sheet.dataset.rowId,'r3');assert.deepEqual(shown(),['r3']);
  h.fire(row('r2'),'pointerenter');assert.deepEqual(shown(),['r3']);
  h.timers.at(-1)();
  assert.equal(sheet.dataset.rowId,'r2');assert.deepEqual(shown(),['r2']);
  h.fire('workBuddyPickerLayer','pointerleave');
  assert.equal(sheet.dataset.rowId,'r1');assert.deepEqual(shown(),['r1']);
  assert.equal(row('r1').attributes['aria-current'],'true');assert.equal(row('r2').attributes['aria-current'],'false');
  assert.deepEqual(plain(h.run('Array.from(workBuddyAssignments)')),original);
});

test('filtered candidates regain the displayed-row highlight when the selected sheet is already mounted',()=>{
  const h=buddyViewHarness(),sheet=h.get('workBuddyHoverPreview'),search=h.get('workBuddyCaseSearch'),options=h.get('workBuddyCaseOptions');
  const shown=()=>options.children.filter(item=>item.className.split(/\s+/).includes('is-preview')).map(item=>item.dataset.rowId);
  search.value='PD1-CA3';h.fire(search,'input');
  assert.equal(sheet.dataset.rowId,'r1');assert.deepEqual(shown(),[]);
  assert.equal(options.children[0].attributes['aria-current'],'false');
  h.fire(options.children[0],'pointerenter');h.timers.at(-1)();
  assert.deepEqual(shown(),['r3']);
  h.fire('workBuddyPickerLayer','pointerleave');
  assert.equal(sheet.dataset.rowId,'r1');assert.deepEqual(shown(),[]);
  const selectedContent=sheet.children;
  search.value='';h.fire(search,'input');
  assert.equal(sheet.children,selectedContent);
  assert.deepEqual(shown(),['r1']);
  const selected=options.children.find(item=>item.dataset.rowId==='r1');h.fire(selected,'focusin');
  assert.equal(sheet.children,selectedContent);assert.deepEqual(shown(),['r1']);
  assert.equal(selected.attributes['aria-current'],'true');
  assert.deepEqual(plain(h.run('workBuddyAssignments.get("a")')),{rowId:'r1',checked:true});
});

test('an unmatched source sheet clears displayed-row highlighting on restore and Bug navigation updates it',()=>{
  const h=buddyViewHarness();h.run('workBuddySelectBug("c")');
  const shown=()=>h.get('workBuddyCaseOptions').children.filter(item=>item.className.split(/\s+/).includes('is-preview')).map(item=>item.dataset.rowId);
  assert.deepEqual(shown(),[]);
  const candidate=h.get('workBuddyCaseOptions').children.find(item=>item.dataset.rowId==='r3');
  h.fire(candidate,'pointerenter');h.timers.at(-1)();assert.deepEqual(shown(),['r3']);
  h.fire('workBuddyPickerLayer','pointerleave');
  assert.deepEqual(shown(),[]);assert.equal(candidate.attributes['aria-current'],'false');
  assert.deepEqual(plain(h.run('workBuddyAssignments.get("c")')),{rowId:'',checked:false});
  h.run('workBuddySelectBug("b")');
  assert.equal(h.get('workBuddyHoverPreview').dataset.rowId,'r2');assert.deepEqual(shown(),['r2']);
});

test('leaving the workspace restores the committed source and cancels pending hover without changing confirmation',()=>{
  const h=buddyViewHarness(value=>{value.rows[1].preconditions='已选用例的前置条件';});
  h.run('workBuddyChooseRow("r2")');
  const assignments=plain(h.run('Array.from(workBuddyAssignments)'));
  const workspace=h.get('workBuddyPickerLayer');
  const hover=h.get('workBuddyHoverPreview');
  assert.equal(hover.hidden,false);assert.equal(hover.dataset.rowId,'r2');
  h.run('workBuddyPreviewRow("r3",true)');assert.equal(hover.dataset.rowId,'r3');
  h.fire('workBuddyPickerLayer','pointerleave');
  assert.equal(h.get('workBuddyPickerLayer'),workspace);assert.equal(hover.hidden,false);assert.equal(hover.dataset.rowId,'r2');
  assert.deepEqual(byClass(hover,'workbuddy-fact').map(item=>item.children[1].textContent),['已选用例的前置条件','操作二','现象二','预期二']);
  assert.match(textOf(hover),/当前用例/);
  assert.equal(h.get('workBuddyDetailCheck').checked,false);
  assert.deepEqual(plain(h.run('Array.from(workBuddyAssignments)')),assignments);
  hover.scrollTop=137;const selectedFacts=hover.children[1];
  const next=h.get('workBuddyCaseOptions').children.find(item=>item.dataset.rowId==='r3');
  h.fire(next,'pointerenter');const stale=h.timers.at(-1);
  h.fire('workBuddyPickerLayer','pointerleave');stale();
  assert.equal(hover.dataset.rowId,'r2');assert.equal(hover.scrollTop,137);assert.equal(hover.children[1],selectedFacts);
  h.fire('workBuddyPickerLayer','pointerleave');
  assert.equal(hover.scrollTop,137);assert.equal(hover.children[1],selectedFacts);
  assert.deepEqual(plain(h.run('Array.from(workBuddyAssignments)')),assignments);
});

test('search and pointer leave restore the committed source even when its candidate is filtered out',()=>{
  const h=buddyViewHarness(),workspace=h.get('workBuddyPickerLayer');
  const assignments=plain(h.run('Array.from(workBuddyAssignments)'));
  h.run('workBuddyPreviewRow("r3",true)');
  const search=h.get('workBuddyCaseSearch');search.value='PD1-CA3';h.fire(search,'input');
  assert.deepEqual(h.get('workBuddyCaseOptions').children.map(item=>item.dataset.rowId),['r3']);
  const hover=h.get('workBuddyHoverPreview');
  assert.equal(hover.hidden,false);assert.equal(hover.dataset.rowId,'r1');
  h.run('workBuddyPreviewRow("r3",true)');search.focus();
  assert.equal(hover.dataset.rowId,'r1');
  h.run('workBuddyPreviewRow("r3",true)');h.fire('workBuddyPickerLayer','pointerleave');
  assert.equal(hover.dataset.rowId,'r1');assert.equal(h.get('workBuddyPickerLayer'),workspace);
  assert.deepEqual(plain(h.run('Array.from(workBuddyAssignments)')),assignments);
});

test('an unmatched Bug keeps an empty source sheet and visible candidates without assigning a source',()=>{
  const h=buddyViewHarness();h.run('workBuddySelectBug("c")');
  const workspace=h.get('workBuddyPickerLayer'),hover=h.get('workBuddyHoverPreview');
  assert.equal(hover.hidden,false);assert.equal(hover.dataset.rowId,'');
  assert.match(textOf(hover),/尚未选择用例/);
  assert.equal(h.get('workBuddyCaseOptions').children.length,3);
  h.run('workBuddyPreviewRow("r3",true)');assert.equal(hover.hidden,false);
  h.fire('workBuddyPickerLayer','pointerleave');
  assert.equal(h.get('workBuddyPickerLayer'),workspace);assert.equal(hover.hidden,false);assert.equal(hover.dataset.rowId,'');
  assert.match(textOf(hover),/尚未选择用例/);
  const candidate=h.get('workBuddyCaseOptions').children.find(item=>item.dataset.rowId==='r3');
  h.fire(candidate,'pointerenter');const stale=h.timers.at(-1);
  h.fire('workBuddyPickerLayer','pointerleave');stale();
  assert.equal(hover.hidden,false);assert.equal(hover.dataset.rowId,'');
  assert.deepEqual(plain(h.run('workBuddyAssignments.get("c")')),{rowId:'',checked:false});
  assert.equal(h.get('workBuddyDetailCheck').disabled,true);
});

test('keyboard candidate browsing previews on focus and arrow keys commit only after Enter',()=>{
  const h=buddyViewHarness();
  const options=h.get('workBuddyCaseOptions'),third=options.children.find(item=>item.dataset.rowId==='r3').children[0];
  third.focus();
  assert.equal(h.get('workBuddyHoverPreview').hidden,false);
  assert.equal(h.get('workBuddyHoverPreview').dataset.rowId,'r3');
  assert.deepEqual(plain(h.run('workBuddyAssignments.get("a")')),{rowId:'r1',checked:true});
  const arrow=h.fire(third,'keydown',{key:'ArrowUp'});
  assert.equal(arrow.defaultPrevented,true);
  const second=options.children.find(item=>item.dataset.rowId==='r2').children[0];
  assert.equal(h.context.document.activeElement,second);
  assert.equal(h.get('workBuddyHoverPreview').dataset.rowId,'r2');
  assert.deepEqual(plain(h.run('workBuddyAssignments.get("a")')),{rowId:'r1',checked:true});
  const enter=h.fire(second,'keydown',{key:'Enter'});
  assert.equal(enter.defaultPrevented,true);
  assert.deepEqual(plain(h.run('workBuddyAssignments.get("a")')),{rowId:'r2',checked:false});
  assert.equal(h.get('workBuddyHoverPreview').hidden,false);
  assert.equal(h.get('workBuddyHoverPreview').dataset.rowId,'r2');
  assert.equal(h.get('workBuddyCaseOptions'),options);
  assert.equal(h.context.document.activeElement,second);
  assert.match(textOf(h.get('workBuddyHoverPreview')),/现象二/);
});

test('source selection commits in place and selecting the same source retains confirmation and the persistent sheet',()=>{
  const h=buddyViewHarness(),search=h.get('workBuddyCaseSearch'),options=h.get('workBuddyCaseOptions'),hover=h.get('workBuddyHoverPreview');
  options.scrollTop=94;
  h.run('workBuddyPreviewRow("r3",true)');
  const use=h.get('workBuddyHoverPreview').children[0].children[1];h.fire(use,'click');
  assert.deepEqual(plain(h.run('workBuddyAssignments.get("a")')),{rowId:'r3',checked:false});
  assert.equal(h.get('workBuddyCaseSearch'),search);assert.equal(h.get('workBuddyCaseOptions'),options);assert.equal(h.get('workBuddyHoverPreview'),hover);
  assert.equal(options.scrollTop,94);assert.equal(hover.hidden,false);assert.equal(hover.dataset.rowId,'r3');
  assert.match(textOf(hover),/当前用例/);
  assert.equal(hover.children[0].children[1].tagName,'span');
  h.get('workBuddyDetailCheck').checked=true;h.fire('workBuddyDetailCheck','change');
  hover.scrollTop=73;h.run('workBuddyPreviewRow("r2",true)');
  const current=h.get('workBuddyCaseOptions').children.find(item=>item.dataset.rowId==='r3');h.fire(current,'click');
  assert.equal(h.get('workBuddyCaseOptions'),options);assert.equal(h.get('workBuddyHoverPreview'),hover);
  assert.equal(hover.hidden,false);assert.equal(hover.dataset.rowId,'r3');assert.equal(hover.scrollTop,73);
  assert.deepEqual(plain(h.run('workBuddyAssignments.get("a")')),{rowId:'r3',checked:true});
});

test('the sole source sheet keeps notes and raw evidence specific to the displayed candidate',()=>{
  const h=buddyViewHarness(value=>{
    Object.assign(value.rows[0],{review_notes:['已选来源的待确认说明'],source_actual:'已选来源的原始备注'});
    Object.assign(value.rows[2],{review_notes:['候选来源的待确认说明'],warnings:['候选来源的步骤提醒'],source_actual:'候选来源的原始备注'});
  });
  const sheet=h.get('workBuddyHoverPreview');
  assert.match(textOf(sheet),/已选来源的待确认说明/);
  h.run('workBuddyPreviewRow("r3",true)');
  assert.equal(h.get('workBuddyHoverPreview'),sheet);
  assert.match(textOf(sheet),/候选来源的待确认说明/);assert.match(textOf(sheet),/候选来源的步骤提醒/);assert.match(textOf(sheet),/候选来源的原始备注/);
  assert.doesNotMatch(textOf(sheet),/已选来源的待确认说明|已选来源的原始备注/);
  assert.ok(!byClass(sheet,'workbuddy-review-notes')[0].open);assert.ok(!byClass(sheet,'workbuddy-evidence')[0].open);
  assert.doesNotMatch(byClass(sheet,'workbuddy-fact').map(textOf).join(' '),/待确认说明|步骤提醒|原始备注/);
  h.fire('workBuddyPickerLayer','pointerleave');
  assert.match(textOf(sheet),/已选来源的待确认说明/);assert.match(textOf(sheet),/已选来源的原始备注/);
  assert.doesNotMatch(textOf(sheet),/候选来源的待确认说明|候选来源的原始备注/);
  assert.deepEqual(plain(h.run('workBuddyAssignments.get("a")')),{rowId:'r1',checked:true});
});

test('focusing or changing confirmation restores the committed source before review',()=>{
  const h=buddyViewHarness(),sheet=h.get('workBuddyHoverPreview'),check=h.get('workBuddyDetailCheck');
  sheet.scrollTop=88;h.run('workBuddyPreviewRow("r3",true)');
  assert.equal(sheet.dataset.rowId,'r3');
  check.focus();
  assert.equal(sheet.dataset.rowId,'r1');assert.equal(sheet.scrollTop,88);
  assert.deepEqual(plain(h.run('workBuddyAssignments.get("a")')),{rowId:'r1',checked:true});
  h.run('workBuddyPreviewRow("r2",true)');check.checked=false;h.fire(check,'change');
  assert.equal(sheet.dataset.rowId,'r1');assert.equal(sheet.scrollTop,88);
  assert.deepEqual(plain(h.run('workBuddyAssignments.get("a")')),{rowId:'r1',checked:false});
});

test('stale hover callbacks cannot replace the source sheet after selection or plan lifecycle changes',()=>{
  const transitions={
    'choose a source':h=>h.run('workBuddyChooseRow("r2")'),
    'navigate to another Bug':h=>h.run('workBuddyNavigate(1)'),
    'begin an import':h=>h.run('workBuddySetBusy(true)'),
    'disconnect':h=>h.run('workBuddyStatus.enabled=false;workBuddyAcceptStatus()'),
    'receive a new plan':h=>h.run('workBuddyStatus.pending={...original,plan_id:"new"};workBuddyAcceptStatus()'),
    'replace the active plan':h=>h.run('workBuddyPlan={...original,plan_id:"replacement"}'),
  };
  for(const [name,transition] of Object.entries(transitions)){
    const h=buddyViewHarness();
    const candidate=h.get('workBuddyCaseOptions').children.find(item=>item.dataset.rowId==='r3');
    h.fire(candidate,'pointerenter');const stale=h.timers.at(-1);
    transition(h);stale();
    assert.notEqual(h.get('workBuddyHoverPreview').dataset.rowId,'r3',name);
  }
});

test('inactive or stale sessions cannot preview or commit another source',()=>{
  const transitions={
    busy:'workBuddySetBusy(true)',
    disconnected:'workBuddyStatus.enabled=false;workBuddyAcceptStatus()',
    consumed:'workBuddyStatus.pending=null;workBuddyAcceptStatus()',
    stale:'workBuddyStatus.pending={...original,plan_id:"new"};workBuddyAcceptStatus()',
    closed:'workBuddyDialog.open=false',
  };
  for(const [name,transition] of Object.entries(transitions)){
    const h=buddyViewHarness(),before=plain(h.run('Array.from(workBuddyAssignments)'));
    h.run(transition);h.run('workBuddyPreviewRow("r3",true);workBuddyChooseRow("r3");workBuddyPreviewRow("r3")');
    h.timers.at(-1)();
    assert.equal(h.get('workBuddyHoverPreview').dataset.rowId,'r1',name);
    assert.deepEqual(plain(h.run('Array.from(workBuddyAssignments)')),before,name);
  }
});

test('expired or stale status disables source controls and reverts a late native radio change',()=>{
  const transitions={
    expired:'workBuddyStatus.enabled=false;workBuddyAcceptStatus()',
    stale:'workBuddyStatus.pending={...original,plan_id:"new"};workBuddyAcceptStatus()',
  };
  for(const [name,transition] of Object.entries(transitions)){
    const h=buddyViewHarness(),options=h.get('workBuddyCaseOptions'),controls=options.children.map(item=>item.children[0]);
    const selected=controls.find(item=>item.value==='r1'),late=controls.find(item=>item.value==='r3');
    assert.ok(controls.every(item=>!item.disabled),name);assert.equal(h.get('workBuddyClearCase').disabled,false,name);
    h.run('workBuddyPreviewRow("r3",true)');h.run(transition);
    assert.ok(controls.every(item=>item.disabled),name);assert.equal(h.get('workBuddyClearCase').disabled,true,name);
    selected.checked=false;late.checked=true;h.fire(late,'change');
    assert.equal(selected.checked,true,name);assert.equal(late.checked,false,name);
    assert.equal(selected.parentElement.className.split(/\s+/).includes('selected'),true,name);
    assert.equal(late.parentElement.className.split(/\s+/).includes('selected'),false,name);
    assert.ok(controls.every(item=>item.disabled),name);
    assert.deepEqual(plain(h.run('workBuddyAssignments.get("a")')),{rowId:'r1',checked:true},name);
    assert.equal(h.get('workBuddyHoverPreview').dataset.rowId,'r1',name);
    h.run('workBuddyStatus={enabled:true,pending:original};workBuddyAcceptStatus()');
    assert.ok(controls.every(item=>!item.disabled),name);assert.equal(h.get('workBuddyClearCase').disabled,false,name);
    assert.equal(selected.checked,true,name);assert.equal(late.checked,false,name);
  }
});

test('the left list counts eligible Bugs independently of received cases and retains unmatched Bugs',()=>{
  const h=buddyViewHarness(value=>value.bugs.push({id:'d',title:'今天第四个附件文件夹'},{id:'submitted',title:'已经提交',remote_id:'123',status:'submitted'}));
  assert.deepEqual(h.get('workBuddyBugs').children.map(item=>item.dataset.bugId),['a','b','c','d']);
  const summary=textOf(h.get('workBuddySummary'));
  for(const value of ['本批次 4 个 Bug','待匹配 2 个'])assert.ok(summary.includes(value),summary);
  assert.match(h.get('workBuddySummary').title,/已匹配 2 个 Bug · 收到 3 条用例/);
  h.run('workBuddySelectBug("d")');
  assert.equal(h.run('workBuddyBug().id'),'d');
  assert.equal(h.run('workBuddyRow()'),undefined);
  assert.equal(h.get('workBuddyCaseOptions').children.length,3);
  assert.equal(h.get('workBuddyDetailCheck').disabled,true);
  assert.match(textOf(h.get('workBuddyHoverPreview')),/尚未选择用例/);
});

test('equally ranked candidates require a choice instead of arbitrarily selecting the first case',()=>{
  for(const match_type of ['suggested','exact_id']){
    const h=buddyViewHarness(value=>{
      value.rows[1].match_type=match_type;
      Object.assign(value.rows[2],{suggested_bug_id:'b',match_type});
    });
    assert.deepEqual(plain(h.run('workBuddyAssignments.get("b")')),{rowId:'',checked:false});
    h.run('workBuddySelectBug("b")');
    assert.equal(h.get('workBuddyDetailCheck').disabled,true);
    assert.deepEqual(h.get('workBuddyCaseOptions').children.map(item=>item.children[0].checked),[false,false,false]);
    const radio=h.get('workBuddyCaseOptions').children[1].children[0];radio.checked=true;h.fire(radio,'change');
    assert.deepEqual(plain(h.run('workBuddyAssignments.get("b")')),{rowId:'r3',checked:false});
    assert.equal(h.get('workBuddyDetailCheck').disabled,false);
  }
});

test('navigating Bugs keeps the compact list and restores each Bug detail scroll position',()=>{
  const h=buddyViewHarness(),firstListItem=h.get('workBuddyBugs').children[0];
  h.get('workBuddyBugs').scrollTop=240;h.get('workBuddyHoverPreview').scrollTop=87;
  h.run('workBuddyPreviewRow("r3",true)');h.get('workBuddyHoverPreview').scrollTop=196;
  h.run('workBuddyNavigate(1)');
  assert.equal(h.run('workBuddyCurrentBugId'),'b');
  assert.equal(h.get('workBuddyHoverPreview').dataset.bugId,'b');
  assert.equal(h.get('workBuddyBugs').children[0],firstListItem);
  assert.equal(h.get('workBuddyBugs').scrollTop,240);
  assert.equal(h.get('workBuddyHoverPreview').scrollTop,0);
  h.get('workBuddyHoverPreview').scrollTop=51;h.run('workBuddyNavigate(-1)');
  assert.equal(h.get('workBuddyHoverPreview').scrollTop,87);
  assert.equal(h.get('workBuddyPrevious').disabled,true);
});

test('case search narrows candidates and choosing another source clears Bug confirmation',()=>{
  const h=buddyViewHarness();
  h.get('workBuddyCaseSearch').value='现象三';h.fire('workBuddyCaseSearch','input');
  assert.equal(h.get('workBuddyCaseOptions').children.length,1);
  assert.deepEqual(plain(h.run('workBuddyAssignments.get("a")')),{rowId:'r1',checked:true});
  const radio=h.get('workBuddyCaseOptions').children[0].children[0];radio.checked=true;h.fire(radio,'change');
  assert.deepEqual(plain(h.run('workBuddyAssignments.get("a")')),{rowId:'r3',checked:false});
  assert.equal(h.run('workBuddyAssociation(workBuddyBug()).kind'),'manual');
  assert.match(textOf(h.get('workBuddyHoverPreview')),/操作三/);
  assert.equal(h.get('workBuddyDetailCheck').checked,false);
  assert.match(textOf(h.get('workBuddySummary')),/已核对 0 个/);
  h.run('workBuddyNavigate(1);workBuddyNavigate(-1)');
  assert.equal(h.get('workBuddyCaseSearch').value,'现象三');
  assert.equal(h.get('workBuddyCaseOptions').children.length,1);
});

test('Bug search, unchecked and unmatched filters preserve choices while changing the view',()=>{
  const h=buddyViewHarness(),initial=plain(h.run('Array.from(workBuddyAssignments)'));
  h.get('workBuddySearch').value='完整长标题';h.fire('workBuddySearch','input');
  assert.equal(h.run('workBuddyCurrentBugId'),'b');assert.equal(h.get('workBuddyBugs').children.length,1);
  h.get('workBuddyUncheckedOnly').checked=true;h.fire('workBuddyUncheckedOnly','change');
  assert.deepEqual(plain(h.run('Array.from(workBuddyAssignments)')),initial);
  h.get('workBuddyDetailCheck').checked=true;h.fire('workBuddyDetailCheck','change');
  assert.equal(h.run('workBuddyVisibleBugs().length'),0);
  assert.equal(h.run('workBuddySelected().length'),2);
  h.get('workBuddySearch').value='';h.fire('workBuddySearch','input');
  h.get('workBuddyUncheckedOnly').checked=false;h.fire('workBuddyUncheckedOnly','change');
  h.get('workBuddyUnmatchedOnly').checked=true;h.fire('workBuddyUnmatchedOnly','change');
  assert.deepEqual(plain(h.run('workBuddyVisibleBugs().map(bug=>bug.id)')),['c']);
  assert.deepEqual(plain(h.run('workBuddyAssignments.get("a")')),{rowId:'r1',checked:true});
  assert.deepEqual(plain(h.run('workBuddyAssignments.get("b")')),{rowId:'r2',checked:true});
  assert.deepEqual(plain(h.run('workBuddyAssignments.get("c")')),{rowId:'',checked:false});
});

test('separately checked Bugs can reuse one source case and send separate import assignments',async()=>{
  const h=buddyViewHarness();h.run('workBuddySelectBug("b");workBuddyChooseRow("r1")');
  h.get('workBuddyDetailCheck').checked=true;h.fire('workBuddyDetailCheck','change');
  assert.deepEqual(plain(h.run('workBuddySelected().map(bug=>bug.id)')),['a','b']);
  assert.match(textOf(h.get('workBuddyApply')),/导入已核对 Bug（2）/);
  h.context.api=async(route,data)=>{h.calls.push({route,data});return {state:{bugs:[]},applied:2,remaining_bugs:1,pending:plan('remaining',h.context.original.rows,[h.context.original.bugs[2]])};};
  await h.run('workBuddyApply()');
  assert.deepEqual(plain(h.calls[0]),{route:'/api/workbuddy/apply',data:{plan_id:'view',review_scope:'bugs',assignments:[{row_id:'r1',bug_id:'a',mode:'fill'},{row_id:'r1',bug_id:'b',mode:'fill'}]}});
  assert.deepEqual(plain(h.run('Array.from(workBuddyAssignments.keys())')),['c']);
  assert.equal(h.run('workBuddyPlan.rows.length'),3);
});

test('lightweight polling leaves active case search, source preview and scroll positions mounted',async()=>{
  const h=buddyViewHarness();h.run('workBuddySelectBug("b")');
  const search=h.get('workBuddyCaseSearch'),preview=h.get('workBuddyHoverPreview'),list=h.get('workBuddyBugs');
  search.value='正在输入的用例名称';search.focus();preview.scrollTop=129;list.scrollTop=211;
  h.context.api=async()=>({enabled:true,pending:{plan_id:'view',unchanged:true}});
  await h.run('workBuddyPoll()');
  assert.equal(h.get('workBuddyCaseSearch'),search);assert.equal(h.context.document.activeElement,search);
  assert.equal(h.get('workBuddyCaseSearch').value,'正在输入的用例名称');
  assert.equal(h.get('workBuddyHoverPreview'),preview);
  assert.equal(preview.scrollTop,129);assert.equal(list.scrollTop,211);
});
