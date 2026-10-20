/* Exercise folder relinking decisions without touching real user data or a server. */
"use strict";
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const plain=value=>JSON.parse(JSON.stringify(value));

function samplePlan() {
  return {
    plan_id:'plan-1',root_dir:'D:\\evidence\\new-date',batch_key:'new-batch',
    targets:[{folder_name:'new folder A',folder:'D:\\evidence\\new-date\\new folder A'},
      {folder_name:'folder B',folder:'D:\\evidence\\new-date\\folder B'}],
    sources:[{source_batch_key:'old-batch',bug_id:'bug-a',title:'Edited report A',original_title:'folder A',
      old_folder:'D:\\evidence\\old-date\\folder A',source_root:'D:\\evidence\\old-date',status:'submitted',remote_id:'123',review_token:'token-a'},
      {source_batch_key:'old-batch',bug_id:'bug-b',title:'Edited report B',original_title:'folder B',
      old_folder:'D:\\evidence\\old-date\\folder B',source_root:'D:\\evidence\\old-date',status:'needs_review',review_token:'token-b'}]
  };
}

function harness(plan=samplePlan()) {
  const elements=new Map(),calls=[];
  let document;
  function create(tag) {
    let id='',ownText='';
    const item={tagName:tag,children:[],listeners:{},attributes:{},value:'',disabled:false,open:false,
      get textContent(){return ownText+this.children.map(child=>child.textContent).join('');},
      set textContent(value){ownText=String(value);this.children=[];},
      get innerHTML(){throw new Error('Relinking must never read HTML');},
      set innerHTML(value){throw new Error('Relinking must never render HTML');},
      get id(){return id;},set id(value){id=value;elements.set(value,this);},
      setAttribute(key,value){this.attributes[key]=String(value);},
      addEventListener(name,listener){(this.listeners[name]||=[]).push(listener);},
      append(...children){this.children.push(...children);children.forEach(child=>{child.parentElement=this;});},
      replaceChildren(...children){ownText='';this.children=[];this.append(...children);},
      remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(child=>child!==this);},
      focus(){document.activeElement=this;fire(this,'focus');},
      showModal(){this.open=true;},
      close(){if(!this.open)return;this.open=false;fire(this,'close');}
    };
    return item;
  }
  document={createElement:create,body:create('body'),activeElement:create('button')};
  const previousFocus=document.activeElement;
  const node=(tag,className='',content)=>{const item=create(tag);item.className=className;if(content!==undefined)item.textContent=content;return item;};
  const context={document,Map,Set,Promise,Number,String,Array,
    node,button:(text,className,action)=>{const item=node('button',className,text);if(action)item.addEventListener('click',action);return item;},
    api:async(route,data)=>{calls.push({route,data:plain(data)});return structuredClone(plan);},
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'..','web','relink.js'),'utf8'),context,{filename:'relink.js'});
  function fire(item,type,detail={}) {
    if(typeof item==='string')item=elements.get(item);
    assert.ok(item,'element exists');
    const event={target:item,defaultPrevented:false,preventDefault(){this.defaultPrevented=true;},...detail};
    for(const listener of item.listeners[type]||[])listener(event);
    if(type==='cancel'&&!event.defaultPrevented)item.close();
    return event;
  }
  return {context,document,previousFocus,calls,fire,get:id=>elements.get(id),
    run:source=>vm.runInContext(source,context),
    choose:()=>vm.runInContext('chooseScanRelinks("D:\\\\evidence\\\\new-date")',context),
    select(id,value){const element=elements.get(id);assert.ok(element);element.focus();element.value=value;fire(element,'change');},
  };
}

test('preview without new folders or missing old records proceeds without opening a dialog',async()=>{
  for(const field of ['targets','sources']) {
    const plan=samplePlan();plan[field]=[];const h=harness(plan);
    assert.deepEqual(plain(await h.choose()),{path:'D:\\evidence\\new-date'});
    assert.equal(h.document.body.children.length,0);
    assert.deepEqual(h.calls.map(call=>call.route),['/api/scan/preview']);
  }
});

test('default decision creates new Bugs even for an exact same name; confirming carries no relink',async()=>{
  const h=harness();const result=h.choose();await tick();
  assert.equal(h.get('scanRelinkTarget-0').value,'');
  assert.equal(h.get('scanRelinkTarget-1').value,'');
  assert.match(h.get('scanRelinkHint').textContent,/0 条沿用旧记录/);
  h.fire('scanRelinkConfirm','click');
  assert.deepEqual(plain(await result),{path:'D:\\evidence\\new-date'});
  assert.equal(h.document.activeElement,h.previousFocus);
});

test('cancel button, close button and Escape abandon the scan without a mutation request',async()=>{
  for(const cancel of ['scanRelinkCancel','scanRelinkClose','escape']) {
    const h=harness();
    h.context.testScan=payload=>h.calls.push({route:'/api/scan',data:plain(payload)});
    const result=h.run('(async()=>{const payload=await chooseScanRelinks("test-path");if(payload)return testScan(payload);return null;})()');
    await tick();
    h.select('scanRelinkTarget-0','0');
    if(cancel==='escape')h.fire('scanRelinkDialog','cancel');else h.fire(cancel,'click');
    assert.equal(await result,null);
    assert.deepEqual(h.calls.map(call=>call.route),['/api/scan/preview']);
    assert.equal(h.document.body.children.length,0);
    assert.equal(h.run('scanRelinkChoosing'),false);
  }
});

test('manual relinking displays old title, folder and submission and sends the preview snapshots',async()=>{
  const h=harness();const result=h.choose();await tick();
  h.select('scanRelinkTarget-0','0');
  const detail=h.get('scanRelinkDetail-0').textContent;
  assert.match(detail,/Edited report A/);assert.match(detail,/old-date\\folder A/);
  assert.match(detail,/已提交 · 禅道 #123/);
  h.fire('scanRelinkConfirm','click');
  assert.deepEqual(plain(await result),{path:'D:\\evidence\\new-date',relink_plan_id:'plan-1',relinks:[
    {folder_name:'new folder A',source_batch_key:'old-batch',bug_id:'bug-a',review_token:'token-a'}
  ]});
  assert.deepEqual(h.calls.map(call=>call.route),['/api/scan/preview']);
});

test('one old Bug cannot be chosen twice, including a synthetic invalid change event',async()=>{
  const h=harness();const result=h.choose();await tick();
  h.select('scanRelinkTarget-0','0');
  h.get('scanRelinkTarget-1').focus();
  assert.equal(h.get('scanRelinkTarget-1').children[1].disabled,true);
  h.select('scanRelinkTarget-1','0');
  assert.equal(h.get('scanRelinkTarget-1').value,'');
  assert.match(h.get('scanRelinkAnnouncement').textContent,/已被占用/);
  h.select('scanRelinkTarget-0','');
  h.get('scanRelinkTarget-1').focus();
  assert.equal(h.get('scanRelinkTarget-1').children[1].disabled,false);
  h.fire('scanRelinkCancel','click');await result;
});

test('manual selections cannot mix source batches and reset unlocks the other batch',async()=>{
  const plan=samplePlan();plan.sources[1].source_batch_key='another-batch';plan.sources[1].source_root='D:\\other';
  const h=harness(plan);const result=h.choose();await tick();
  h.select('scanRelinkTarget-0','0');
  h.get('scanRelinkTarget-1').focus();
  assert.equal(h.get('scanRelinkTarget-1').children.some(option=>option.value==='1'),false);
  h.select('scanRelinkTarget-1','1');assert.equal(h.get('scanRelinkTarget-1').value,'');
  h.select('scanRelinkBatch','another-batch');assert.equal(h.get('scanRelinkMatch').disabled,true);
  h.fire('scanRelinkReset','click');
  assert.equal(h.get('scanRelinkTarget-1').children.find(option=>option.value==='1').disabled,false);
  h.select('scanRelinkTarget-1','1');assert.equal(h.get('scanRelinkTarget-1').value,'1');
  h.fire('scanRelinkCancel','click');await result;
});

test('same-name batch migration needs an explicit click and uses original names, not edited titles',async()=>{
  const plan=samplePlan();plan.targets[0].folder_name='folder A';
  const h=harness(plan);const result=h.choose();await tick();
  h.select('scanRelinkBatch','old-batch');
  assert.equal(h.get('scanRelinkTarget-0').value,'');assert.equal(h.get('scanRelinkTarget-1').value,'');
  h.fire('scanRelinkMatch','click');
  assert.equal(h.get('scanRelinkTarget-0').value,'0');assert.equal(h.get('scanRelinkTarget-1').value,'1');
  assert.match(h.get('scanRelinkAnnouncement').textContent,/已匹配 2 条/);
  h.fire('scanRelinkConfirm','click');const payload=plain(await result);
  assert.equal(payload.relinks.length,2);assert.equal(payload.relinks[0].bug_id,'bug-a');
});

test('same-name matching leaves duplicate or approximate old names for manual review',async()=>{
  const plan=samplePlan();plan.targets[0].folder_name='folder A';
  plan.sources.push({...plan.sources[0],bug_id:'duplicate-a',review_token:'duplicate-token'});
  plan.sources[1].original_title='folder B similar';
  const h=harness(plan);const result=h.choose();await tick();
  h.select('scanRelinkBatch','old-batch');h.fire('scanRelinkMatch','click');
  assert.equal(h.get('scanRelinkTarget-0').value,'');assert.equal(h.get('scanRelinkTarget-1').value,'');
  assert.match(h.get('scanRelinkAnnouncement').textContent,/没有找到/);
  h.fire('scanRelinkCancel','click');await result;
});

test('missing optional metadata and hostile folder text remain ordinary readable text',async()=>{
  const plan=samplePlan();plan.targets[0].folder_name='<img src=x onerror=alert(1)>';
  plan.sources[0].title=undefined;plan.sources[0].remote_id=undefined;
  plan.sources[0].settings_note='<script>secret</script>';
  const h=harness(plan);const result=h.choose();await tick();
  h.select('scanRelinkTarget-0','0');
  const text=h.get('scanRelinkDialog').textContent;
  assert.ok(text.includes('<img src=x onerror=alert(1)>'));
  assert.ok(text.includes('<script>secret</script>'));
  assert.ok(!text.includes('undefined'));assert.ok(!text.includes('null'));
  h.fire('scanRelinkCancel','click');await result;
});

test('an invalid preview fails before offering an unsafe relink and releases its local guard',async()=>{
  const plan=samplePlan();delete plan.sources[0].review_token;const h=harness(plan);
  await assert.rejects(h.choose(),/关联信息不完整/);
  assert.equal(h.run('scanRelinkChoosing'),false);
  assert.equal(h.document.body.children.length,0);
});

test('300 folders keep only one expanded candidate selector and preserve choices on focus changes',async()=>{
  const plan=samplePlan();
  plan.targets=Array.from({length:300},(_,index)=>({folder_name:'folder '+index}));
  plan.sources=Array.from({length:300},(_,index)=>({...plan.sources[0],bug_id:'bug-'+index,original_title:'folder '+index,review_token:'token-'+index}));
  const h=harness(plan);const result=h.choose();await tick();
  const optionCount=()=>Array.from({length:300},(_,index)=>h.get('scanRelinkTarget-'+index).children.length).reduce((a,b)=>a+b,0);
  assert.equal(optionCount(),300);
  h.select('scanRelinkTarget-0','0');h.get('scanRelinkTarget-299').focus();
  assert.ok(optionCount()<=601);
  assert.equal(h.get('scanRelinkTarget-0').value,'0');
  assert.equal(h.get('scanRelinkTarget-0').children.length,2);
  h.fire('scanRelinkCancel','click');await result;
});

test('an oversized preview is bounded, explains omitted folders and refuses unsafe same-name matching',async()=>{
  const plan=samplePlan();
  plan.targets=Array.from({length:305},(_,index)=>({folder_name:'folder '+index}));
  plan.sources=Array.from({length:305},(_,index)=>({...plan.sources[0],bug_id:'bug-'+index,original_title:'folder '+index,review_token:'token-'+index}));
  const h=harness(plan);const result=h.choose();await tick();
  assert.equal(h.get('scanRelinkTarget-299').children.length,1);
  assert.equal(h.get('scanRelinkTarget-300'),undefined);
  assert.match(h.get('scanRelinkDialog').textContent,/最多显示 300/);
  assert.match(h.get('scanRelinkHint').textContent,/305 条作为新 Bug/);
  h.select('scanRelinkBatch','old-batch');assert.equal(h.get('scanRelinkMatch').disabled,true);
  h.fire('scanRelinkMatch','click');assert.equal(h.get('scanRelinkTarget-0').value,'');
  h.fire('scanRelinkConfirm','click');assert.deepEqual(plain(await result),{path:'D:\\evidence\\new-date'});
});
