/* WorkBuddy connection is enabled explicitly; proposals never submit or review Bugs. */
"use strict";

let workBuddyDialog=null;
let workBuddyStatus={enabled:false,pending:null};
let workBuddyPlan=null;
let workBuddyAssignments=new Map();
let workBuddyBusy=false;
let workBuddyTimer=null;
let workBuddySerial=0;
let workBuddyStatusBusy=false;
let workBuddyReplaceContent=false;
let workBuddyCurrentBugId='';
let workBuddySearch='';
let workBuddyUncheckedOnly=false;
let workBuddyListNodes=new Map();
let workBuddyCaseQueries=new Map();
let workBuddyUnmatchedOnly=false;
let workBuddyDetailPositions=new Map();
let workBuddyHoverSerial=0;
let workBuddyHoverTimer=null;

function installWorkBuddy(){
  const trigger=$('workBuddyButton');
  if(trigger&&!trigger.dataset.workBuddyBound){trigger.dataset.workBuddyBound='true';trigger.addEventListener('click',openWorkBuddy);}
  if(workBuddyDialog)return;
  const dialog=node('dialog','modal workbuddy-modal workbuddy-review-modal');dialog.id='workBuddyDialog';dialog.setAttribute('aria-labelledby','workBuddyTitle');
  const head=node('div','modal-header workbuddy-header'),heading=node('div','workbuddy-heading');
  const title=node('h2','','WorkBuddy 整理 Bug');title.id='workBuddyTitle';heading.append(title);
  const close=button('','icon-button',()=>dialog.close(),'close');close.id='workBuddyClose';close.setAttribute('aria-label','关闭 WorkBuddy 整理');head.append(heading,close);
  const body=node('div','modal-body workbuddy-body');body.id='workBuddyBody';
  const top=node('div','workbuddy-top');top.id='workBuddyTop';
  const connectionBar=node('div','workbuddy-connectionbar');
  const status=node('div','workbuddy-status');status.id='workBuddyStatus';status.setAttribute('role','status');
  const controls=node('div','workbuddy-connection-controls');
  const enable=button('开启本机连接（60 分钟）','button primary',workBuddyEnable,'check');enable.id='workBuddyEnable';
  const copy=button('复制任务给 WorkBuddy','button secondary',workBuddyCopyTask,'copy');copy.id='workBuddyCopy';copy.hidden=true;
  const disable=button('断开连接','text-button',workBuddyDisable);disable.id='workBuddyDisable';disable.hidden=true;
  controls.append(enable,copy,disable);
  connectionBar.append(status,controls);
  const task=node('label','field workbuddy-task');task.id='workBuddyTaskArea';task.hidden=true;task.append(node('span','','任务已准备好，也可以直接选中复制'));
  const taskText=node('textarea');taskText.id='workBuddyTaskText';taskText.readOnly=true;taskText.spellcheck=false;taskText.setAttribute('aria-label','给 WorkBuddy 的整理任务');task.append(taskText);
  if(typeof installWorkBuddyGuide==='function')installWorkBuddyGuide(task);
  const error=node('div','notice warning workbuddy-error');error.id='workBuddyError';error.hidden=true;error.setAttribute('role','alert');
  const proposals=node('div','workbuddy-proposals');proposals.id='workBuddyProposals';
  const notice=node('div','workbuddy-notice');notice.id='workBuddyNotice';
  top.append(connectionBar,error,notice);body.append(top,proposals);
  const foot=node('div','modal-footer workbuddy-footer'),hint=node('span','footer-hint');hint.id='workBuddyHint';
  const closeButton=button('关闭','button secondary',()=>dialog.close());closeButton.id='workBuddyCancel';
  const apply=button('导入已核对 Bug（0）','button primary',workBuddyApply,'check');apply.id='workBuddyApply';apply.hidden=true;apply.disabled=true;
  const policy=node('label','workbuddy-footer-policy');policy.id='workBuddyReplaceLabel';policy.hidden=true;
  const replace=node('input');replace.type='checkbox';replace.id='workBuddyReplace';replace.addEventListener('change',()=>{workBuddyCaptureDetailPosition();workBuddyReplaceContent=replace.checked;workBuddyRestoreSelectedPreview();workBuddyRenderStatus();});policy.append(replace,node('span','','覆盖已有内容'));
  const undo=button('撤销上次导入','button secondary',workBuddyUndoImport);undo.id='workBuddyUndo';undo.hidden=true;
  foot.append(hint,undo,policy,closeButton,apply);dialog.append(head,body,foot);document.body.append(dialog);workBuddyDialog=dialog;
  dialog.addEventListener('cancel',event=>{if(workBuddyBusy)event.preventDefault();});
  dialog.addEventListener('close',()=>{clearTimeout(workBuddyTimer);workBuddyTimer=null;++workBuddySerial;workBuddyPlan=null;workBuddyAssignments.clear();workBuddyReplaceContent=false;workBuddyResetView();$('workBuddyProposals').replaceChildren();$('workBuddyTaskText').value='';$('workBuddyTaskArea').hidden=true;});
}

function workBuddyOpenHelp(){if(typeof openWorkBuddyGuide==='function')openWorkBuddyGuide();}

async function openWorkBuddy(){
  if(batchBusy||scanBusy||state.job?.running){toast('请等当前操作完成，再让 WorkBuddy 整理用例。',true);return;}
  if(!state.bugs?.length){toast('先扫描今天的 Bug 附件文件夹，再开启 WorkBuddy 整理。');return;}
  installWorkBuddy();if(workBuddyDialog.open)return;
  try{await flushSave();if(batchBusy||scanBusy||state.job?.running)return;
    workBuddyPlan=null;workBuddyAssignments.clear();workBuddyResetView();workBuddyStatus={enabled:false,pending:null};
    $('workBuddyError').hidden=true;$('workBuddyProposals').replaceChildren();$('workBuddyTaskArea').hidden=true;
    workBuddyRenderWaiting();workBuddySetBusy(false);workBuddyRenderStatus();workBuddyDialog.showModal();
    await workBuddyPoll();
  }catch(error){toast(errorMessage(error),true);}
}

function workBuddyError(message){$('workBuddyError').textContent=message;$('workBuddyError').hidden=false;}

function workBuddySetBusy(value){
  workBuddyBusy=value;if(!workBuddyDialog)return;
  if(value)workBuddyRestoreSelectedPreview();
  workBuddyDialog.setAttribute('aria-busy',String(value));
  workBuddyDialog.querySelectorAll('button,input,select').forEach(control=>{control.disabled=value;});
  if(!value){workBuddyRenderStatus();workBuddyUpdateFooter();workBuddyRefreshListState();workBuddyRefreshNavigation();}
}

function workBuddyTimeLeft(){
  const raw=workBuddyStatus.expires_at;
  const expiry=typeof raw==='number'?raw*(raw<1e12?1000:1):Date.parse(String(raw||''));
  if(!Number.isFinite(expiry))return '本次连接最长有效 60 分钟';
  return '连接约剩 '+Math.max(0,Math.ceil((expiry-Date.now())/60000))+' 分钟';
}

function workBuddyTask(){
  return [
    '使用 bugdesk-workbuddy 技能。',
    '连接文件：'+String(workBuddyStatus.connection_file||''),
    '',
    '读取当前 Bug 清单，根据我在下方粘贴的共享表格失败用例，整理每条 Bug 的前置条件、复现步骤、实际结果和预期结果，保留测试事实和单元格中的换行。',
    '一个 Bug 可以对应多条失败用例。附件文件夹名就是 Bug 的原始标题，经常也会出现在失败备注中，但备注不必与标题逐字一致。请先按原始失败备注识别同一问题，再结合完整 Bug 标题、模块、操作与异常现象判断关联；相同备注是重要依据，近似备注也可结合语义判断并说明理由，不能仅因管理标签一样、标题相似或备注只有“失败”就合并。',
    '请由你把属于同一 Bug 的用例组合起来，每个已匹配 Bug 返回一份完整整理建议，不要逐条返回让我手动组合。按真实流程和结果差异归类，不按用例数量拆场景。前置条件、操作流程、预期和实际相同而只有 query 或参数不同的，用一套公共前置条件和复现步骤，加完整的输入清单；共同预期和实际各写一次。即使有 20 条类似用例，也不要重复写 20 个场景。每条 query、语音原句或参数都要完整保留，可一行一条，不能只留几个示例再写“等”。',
    '只有前置条件、操作流程、预期或实际确实不同时，才按差异分组或单列例外，保持每个输入与其特有结果对应。不同用例分别独立执行，不能串成一次连续操作、增加未记录的重置步骤或猜测共同根因，也不能将未记录的现象推广到全部输入。将全部原始用例及各自事实放进 source_cases 数组；多用例建议的顶层 case_id 留空，不要把多个 ID 拼成一个 ID。',
    '单用例的完整用例 ID 可用于关联；其他匹配只提供建议，说明归并和关联理由，无法确认时留待我核对。实际结果请结合失败用例的操作上下文与明确记录的异常现象整理成自然语句，不要照抄备注或 Bug 标题；去掉版本、厂商归类、模块等管理标签，保留属于界面提示、错误码或原话的括号内容。不能从预期结果反推现象或补造动作、响应、原因。原始失败备注放 source_actual，歧义和待补充事项放 review_notes 数组，不要把【待确认】写入实际结果。没有实际现象则 actual 留空。请使用配套的 bugdesk-workbuddy 1.1.0 技能及其 source_cases 协议。',
    '把整理建议发送到 BugDesk，让我核对合并报告后再导入，不提交到禅道。',
    '',
    '下面是复制的失败用例：',
    '',
  ].join('\n');
}

function workBuddyRenderStatus(){
  if(!workBuddyDialog)return;
  const enabled=!!workBuddyStatus.enabled;
  const status=$('workBuddyStatus');status.classList.toggle('enabled',enabled);
  status.replaceChildren(node('span','workbuddy-dot'),node('strong','',enabled?'本机连接已开启':'本机连接未开启'),node('span','',enabled?workBuddyTimeLeft():'开启后可读取本批次标题、描述和附件名称。'));
  $('workBuddyEnable').hidden=enabled;$('workBuddyCopy').hidden=!enabled;$('workBuddyDisable').hidden=!enabled;
  $('workBuddyHint').textContent='仅填入草稿 · '+(workBuddyReplaceContent?'将覆盖已有内容':'默认保留已有内容');
  workBuddyRenderUndo();
  if(!workBuddyBusy){$('workBuddyEnable').disabled=false;$('workBuddyCopy').disabled=!workBuddyStatus.connection_file;$('workBuddyDisable').disabled=false;}
  if(!enabled){$('workBuddyTaskArea').hidden=true;$('workBuddyTaskText').value='';}
}

async function workBuddyEnable(){
  if(workBuddyBusy)return;
  if(batchBusy||scanBusy||state.job?.running){workBuddyError('请等当前操作完成，再开启连接。');return;}
  ++workBuddySerial;$('workBuddyError').hidden=true;workBuddySetBusy(true);
  try{await flushSave();workBuddyStatus=await api('/api/workbuddy/enable',{});workBuddyAcceptStatus();toast('本机连接已开启，复制任务和失败用例发给 WorkBuddy。');}
  catch(error){workBuddyError(errorMessage(error));}
  finally{workBuddySetBusy(false);workBuddySchedulePoll();}
}

async function workBuddyDisable(){
  if(workBuddyBusy)return;++workBuddySerial;$('workBuddyError').hidden=true;workBuddySetBusy(true);
  try{workBuddyStatus=await api('/api/workbuddy/disable',{});workBuddyPlan=null;workBuddyAssignments.clear();workBuddyResetView();workBuddyRenderWaiting();workBuddyAcceptStatus();toast('WorkBuddy 本机连接已断开，草稿仍保存在 BugDesk。');}
  catch(error){workBuddyError(errorMessage(error));}
  finally{workBuddySetBusy(false);workBuddySchedulePoll();}
}

async function workBuddyCopyTask(){
  if(!workBuddyStatus.enabled||!workBuddyStatus.connection_file)return;
  const text=workBuddyTask();$('workBuddyTaskText').value=text;
  try{if(!navigator.clipboard?.writeText)throw new Error('Clipboard unavailable');await navigator.clipboard.writeText(text);toast('任务已复制，再附上共享表格中复制的失败用例。');}
  catch{$('workBuddyTaskArea').hidden=false;workBuddyOpenHelp();$('workBuddyTaskText').focus();$('workBuddyTaskText').select();toast('任务已展开，按 Ctrl + C 复制后发给 WorkBuddy。');}
}

function workBuddySchedulePoll(){
  clearTimeout(workBuddyTimer);
  if(workBuddyDialog?.open)workBuddyTimer=setTimeout(workBuddyPoll,3000);
}

async function workBuddyPoll(){
  if(!workBuddyDialog?.open)return;
  if(workBuddyBusy||workBuddyStatusBusy){workBuddySchedulePoll();return;}
  const serial=workBuddySerial;workBuddyStatusBusy=true;
  try{
    const known=workBuddyStatus.pending?.plan_id;
    let result=await api('/api/workbuddy/status'+(known?'?known_plan_id='+encodeURIComponent(known):''));
    if(serial!==workBuddySerial||!workBuddyDialog.open)return;
    let merged=workBuddyMergeStatus(result,workBuddyStatus);
    if(!merged){
      result=await api('/api/workbuddy/status');
      if(serial!==workBuddySerial||!workBuddyDialog.open)return;
      merged=workBuddyMergeStatus(result,workBuddyStatus);
      if(!merged)throw new Error('暂时无法读取完整整理建议，请关闭窗口后重新打开。');
    }
    workBuddyStatus=merged;workBuddyAcceptStatus();
  }catch(error){if(serial===workBuddySerial&&workBuddyDialog.open)workBuddyError(errorMessage(error));}
  finally{workBuddyStatusBusy=false;workBuddySchedulePoll();}
}

function workBuddyMergeStatus(incoming,previous){
  const marker=incoming?.pending;
  if(marker?.unchanged===true){
    const cached=previous?.pending;
    if(!cached||String(cached.plan_id)!==String(marker.plan_id)||!Array.isArray(cached.rows)||!Array.isArray(cached.bugs))return null;
    return {...incoming,pending:cached};
  }
  return incoming;
}

function workBuddyAcceptStatus(){
  workBuddyRenderStatus();const pending=workBuddyStatus.pending;
  if(pending&&!workBuddyPlan){workBuddyPlan=pending;workBuddyInitializePlan();workBuddyRenderPlan();}
  const changed=workBuddyPlan&&(!pending||String(pending.plan_id)!==String(workBuddyPlan.plan_id));
  let notice=$('workBuddyNewPlan');
  if(changed){
    workBuddyRestoreSelectedPreview();
    if(!notice){notice=node('div','notice warning workbuddy-new-plan');notice.id='workBuddyNewPlan';$('workBuddyNotice').append(notice);}
    notice.replaceChildren(node('span','',pending?'收到新的整理建议，重新加载后再核对。':'这份整理建议已失效，请重新让 WorkBuddy 整理。'));
    if(pending)notice.append(button('加载新建议','text-button',()=>{workBuddyPlan=workBuddyStatus.pending;workBuddyInitializePlan();workBuddyRenderPlan();},'refresh'));
  }else notice?.remove();
  if(!workBuddyStatus.enabled)workBuddyRestoreSelectedPreview();
  workBuddyUpdateFooter();
}

function workBuddyCanTarget(bug){return !bug.remote_id&&!['submitted','submitting','uncertain','partial'].includes(bug.status);}
function workBuddyResetView(){workBuddyClearHover();workBuddyCurrentBugId='';workBuddySearch='';workBuddyUncheckedOnly=false;workBuddyUnmatchedOnly=false;workBuddyListNodes=new Map();workBuddyCaseQueries=new Map();workBuddyDetailPositions=new Map();}
function workBuddyRows(){return (workBuddyPlan?.rows||[]).slice(0,300);}
function workBuddySources(row){return row?(Array.isArray(row.source_cases)&&row.source_cases.length?row.source_cases:[row]):[];}
function workBuddySourceLabel(row){const sources=workBuddySources(row);return sources.length>1?'已合并 '+sources.length+' 条用例':String(sources[0]?.case_id||row?.case_id||'无用例 ID');}
function workBuddySearchValues(row){return row?[row.case_id,row.title,row.group,row.actual,...workBuddySources(row).flatMap(source=>[source.case_id,source.title,source.group,source.steps,source.actual,source.source_actual])]:[];}
function workBuddyBugs(){return (workBuddyPlan?.bugs||[]).filter(workBuddyCanTarget);}
function workBuddyBug(){return workBuddyBugs().find(bug=>String(bug.id)===workBuddyCurrentBugId);}
function workBuddyRow(bug=workBuddyBug()){
  const rowId=workBuddyAssignments.get(String(bug?.id))?.rowId;
  return workBuddyRows().find(row=>String(row.row_id)===rowId);
}
function workBuddyRank(row,bug){
  if(String(row.suggested_bug_id||'')===String(bug.id))return row.match_type==='exact_id'?3:2;
  return (row.candidate_bug_ids||[]).some(id=>String(id)===String(bug.id))?1:0;
}
function workBuddyCandidateRows(bug,query=''){
  const text=query.trim().toLocaleLowerCase();
  return workBuddyRows().filter(row=>!text||workBuddySearchValues(row).some(value=>String(value||'').toLocaleLowerCase().includes(text)))
    .sort((a,b)=>workBuddyRank(b,bug)-workBuddyRank(a,bug));
}
function workBuddyVisibleBugs(){
  const query=workBuddySearch.trim().toLocaleLowerCase();
  return workBuddyBugs().filter(bug=>{
    if(workBuddyUncheckedOnly&&workBuddyAssignments.get(String(bug.id))?.checked)return false;
    const row=workBuddyRow(bug);
    if(workBuddyUnmatchedOnly&&row)return false;
    return !query||[bug.title,bug.original_title,...workBuddySearchValues(row)].some(value=>String(value||'').toLocaleLowerCase().includes(query));
  });
}
function workBuddyEnsureCurrent(){const visible=workBuddyVisibleBugs();if(!visible.some(bug=>String(bug.id)===workBuddyCurrentBugId))workBuddyCurrentBugId=String(visible[0]?.id||'');}
function workBuddyTitleParts(bug){
  const full=String(bug.title||bug.original_title||'未命名 Bug');
  return {full,title:full,tags:[]};
}
function workBuddyAssociation(bug){
  const row=workBuddyRow(bug);
  if(!row)return {label:'待匹配用例',kind:'unmatched'};
  const rank=workBuddyRank(row,bug);
  return rank===3?{label:'用例 ID 一致',kind:'exact'}:rank>0?{label:'AI 建议 · 请核对',kind:'suggested'}:{label:'已手动选择',kind:'manual'};
}
function workBuddyCaptureDetailPosition(){const scroll=$('workBuddyHoverPreview');if(scroll&&scroll.dataset?.bugId&&scroll.dataset.rowId===String(workBuddyRow()?.row_id||''))workBuddyDetailPositions.set(scroll.dataset.bugId,scroll.scrollTop||0);}

function workBuddyInitializePlan(previousAssignments=null){
  const previousMode=workBuddyReplaceContent;
  workBuddyAssignments=new Map();workBuddyReplaceContent=previousAssignments?previousMode:false;
  const rows=new Set(workBuddyRows().map(row=>String(row.row_id)));
  workBuddyBugs().forEach(bug=>{
    const id=String(bug.id),previous=previousAssignments?.get(id);
    if(previous){const rowId=rows.has(previous.rowId)?previous.rowId:'';workBuddyAssignments.set(id,{rowId,checked:!!rowId&&!!previous.checked});return;}
    const candidates=workBuddyCandidateRows(bug),rank=candidates.length?workBuddyRank(candidates[0],bug):0;
    const unique=rank>0&&candidates.filter(row=>workBuddyRank(row,bug)===rank).length===1;
    workBuddyAssignments.set(id,{rowId:unique?String(candidates[0].row_id):'',checked:unique&&rank===3});
  });
  if(!previousAssignments)workBuddyResetView();
  workBuddyEnsureCurrent();
}

function workBuddyRenderPlan(){
  workBuddyCaptureDetailPosition();
  const area=$('workBuddyProposals');area.replaceChildren();if(!workBuddyPlan){workBuddyRenderWaiting();return;}
  workBuddyDialog?.classList?.toggle('has-plan',true);workBuddyEnsureCurrent();
  const top=node('div','workbuddy-review-topline'),summary=node('div','workbuddy-summary');summary.id='workBuddySummary';summary.setAttribute('role','status');
  const tools=node('div','workbuddy-plan-tools');tools.append(button('勾选已匹配 Bug','text-button',()=>{
    workBuddyBugs().forEach(bug=>{const selection=workBuddyAssignments.get(String(bug.id));if(selection)selection.checked=!!workBuddyRow(bug);});workBuddySelectionChanged();
  }));top.append(summary,tools);
  const grid=node('div','workbuddy-review-grid'),left=node('aside','workbuddy-list-pane');left.setAttribute('aria-label','本批次待整理 Bug');
  const filters=node('div','workbuddy-list-tools');
  const search=node('input','workbuddy-list-search');search.id='workBuddySearch';search.type='search';search.placeholder='搜索 Bug / 用例';search.setAttribute('aria-label','搜索 Bug');search.value=workBuddySearch;
  search.addEventListener('input',()=>{workBuddyCaptureDetailPosition();workBuddySearch=search.value;workBuddyEnsureCurrent();workBuddyRenderList(true);workBuddyRenderDetail();});
  const checks=node('div','workbuddy-list-filters');
  [['workBuddyUncheckedOnly','只看未核对',workBuddyUncheckedOnly],['workBuddyUnmatchedOnly','只看待匹配',workBuddyUnmatchedOnly]].forEach(([id,text,value])=>{
    const label=node('label','workbuddy-unchecked-filter'),input=node('input');input.type='checkbox';input.id=id;input.checked=value;
    input.addEventListener('change',()=>{workBuddyCaptureDetailPosition();if(id==='workBuddyUncheckedOnly')workBuddyUncheckedOnly=input.checked;else workBuddyUnmatchedOnly=input.checked;workBuddyEnsureCurrent();workBuddyRenderList(true);workBuddyRenderDetail();});label.append(input,node('span','',text));checks.append(label);
  });
  const caption=node('small','workbuddy-list-caption');caption.id='workBuddyListCaption';filters.append(search,checks,caption);
  const list=node('div','workbuddy-case-list');list.id='workBuddyBugs';list.setAttribute('role','list');left.append(filters,list);
  const detail=node('section','workbuddy-detail-pane');detail.id='workBuddyDetail';detail.setAttribute('aria-label','当前 Bug 选择用例与内容预览');grid.append(left,detail);area.append(top,grid);
  workBuddyRenderList();workBuddyRenderDetail();workBuddyUpdateFooter();
}

function workBuddyRenderWaiting(){
  const area=$('workBuddyProposals');if(!area)return;
  workBuddyDialog?.classList?.toggle('has-plan',false);
  const waiting=node('div','workbuddy-waiting');waiting.append(icon('layers'),node('h3','','等 WorkBuddy 整理用例'),node('p','','将任务和失败用例发给 WorkBuddy。它会将同一 Bug 的多条用例合并成一份报告，收到后按 Bug 核对整理结果。'));area.replaceChildren(waiting);
}

function workBuddyRenderList(resetScroll=false){
  const list=$('workBuddyBugs');if(!list)return;
  const position=resetScroll?0:list.scrollTop;list.replaceChildren();workBuddyListNodes=new Map();
  const visible=workBuddyVisibleBugs();
  if(!visible.length)list.append(node('div','workbuddy-list-empty','没有符合当前搜索或筛选条件的 Bug。'));
  visible.forEach(bug=>{
    const id=String(bug.id),entry=node('div','workbuddy-case-item workbuddy-bug-item');entry.dataset.bugId=id;entry.setAttribute('role','listitem');
    const check=node('input');check.type='checkbox';check.setAttribute('aria-label','核对 Bug '+(bug.title||bug.original_title||id));check.addEventListener('change',()=>{workBuddyAssignments.get(id).checked=!!workBuddyRow(bug)&&check.checked;workBuddySelectionChanged();});
    const open=button('','workbuddy-case-open',()=>workBuddySelectBug(id));open.setAttribute('aria-label','查看 Bug '+(bug.title||bug.original_title||id));
    const parts=workBuddyTitleParts(bug),identity=node('div','workbuddy-case-identity'),tag=node('span','workbuddy-match-tag');identity.append(tag);
    const title=node('span','workbuddy-case-title',parts.title);title.title=parts.full;
    const association=node('span','workbuddy-case-association');identity.append(association);open.append(title,identity);entry.append(check,open);list.append(entry);
    workBuddyListNodes.set(id,{entry,check,open,tag,association,bug});
  });
  list.scrollTop=position||0;const caption=$('workBuddyListCaption');if(caption){caption.textContent=visible.length===workBuddyBugs().length?'':'显示 '+visible.length+' / '+workBuddyBugs().length;caption.hidden=!caption.textContent;}
  workBuddyRefreshListState();
}

function workBuddyRefreshListState(){
  for(const [id,view] of workBuddyListNodes){
    const selected=workBuddyAssignments.get(id),association=workBuddyAssociation(view.bug),row=workBuddyRow(view.bug);
    view.entry.classList.toggle('active',id===workBuddyCurrentBugId);view.entry.classList.toggle('is-checked',!!selected?.checked);view.check.checked=!!selected?.checked;view.check.disabled=workBuddyBusy||!row;
    view.open.setAttribute('aria-current',id===workBuddyCurrentBugId?'true':'false');view.tag.className='workbuddy-match-tag '+association.kind;view.tag.textContent=selected?.checked?'已核对':row?'待核对':'待匹配';
    view.association.textContent=row?workBuddySourceLabel(row):'';view.association.title=row?String(row.title||''):'';
  }
}

function workBuddySelectionChanged(){
  workBuddyRestoreSelectedPreview();
  if(workBuddyUncheckedOnly){workBuddyCaptureDetailPosition();workBuddyEnsureCurrent();workBuddyRenderList();workBuddyRenderDetail();}
  else{workBuddyRefreshListState();const check=$('workBuddyDetailCheck');if(check)check.checked=!!workBuddyAssignments.get(workBuddyCurrentBugId)?.checked;}
  workBuddyUpdateFooter();
}

function workBuddySelectBug(id){
  if(workBuddyBusy||!workBuddyBugs().some(bug=>String(bug.id)===id))return;
  if(workBuddyCurrentBugId!==id){workBuddyCaptureDetailPosition();workBuddyCurrentBugId=id;workBuddyRefreshListState();workBuddyRenderDetail();}
  workBuddyListNodes.get(id)?.entry.scrollIntoView?.({block:'nearest',inline:'nearest'});
}

function workBuddyChooseRow(rowId){
  if(!workBuddyCanPreview()){workBuddyRefreshSourceState();workBuddyRestoreSelectedPreview();return;}
  if(!workBuddyBug()||(rowId&&!workBuddyRows().some(row=>String(row.row_id)===rowId)))return;
  const bugId=workBuddyCurrentBugId,selection=workBuddyAssignments.get(bugId);if(selection.rowId===rowId){workBuddyRestoreSelectedPreview();return;}
  workBuddyCaptureDetailPosition();workBuddyDetailPositions.set(bugId,0);selection.rowId=rowId;selection.checked=false;workBuddyEnsureCurrent();
  workBuddyRenderList();
  if(workBuddyCurrentBugId!==bugId)workBuddyRenderDetail();
  else{
    workBuddyRefreshSourceState();
    const check=$('workBuddyDetailCheck');if(check)check.checked=false;
    workBuddyRestoreSelectedPreview();
    const selected=Array.from($('workBuddyCaseOptions')?.querySelectorAll('input')||[]).find(radio=>radio.checked);(selected||$('workBuddyCaseSearch'))?.focus();
  }
  workBuddyUpdateFooter();
}

function workBuddyNavigate(direction){
  const bugs=workBuddyVisibleBugs(),index=bugs.findIndex(bug=>String(bug.id)===workBuddyCurrentBugId),target=bugs[index+direction];
  if(target)workBuddySelectBug(String(target.id));
}

function workBuddyRefreshNavigation(){
  const bugs=workBuddyVisibleBugs(),index=bugs.findIndex(bug=>String(bug.id)===workBuddyCurrentBugId);
  const previous=$('workBuddyPrevious'),next=$('workBuddyNext');if(previous)previous.disabled=workBuddyBusy||index<=0;if(next)next.disabled=workBuddyBusy||index<0||index>=bugs.length-1;
}

function workBuddyCancelHover(){
  clearTimeout(workBuddyHoverTimer);workBuddyHoverTimer=null;++workBuddyHoverSerial;
}

function workBuddyClearHover(){
  workBuddyCancelHover();
  const preview=$('workBuddyHoverPreview');if(preview){preview.hidden=true;preview.dataset.rowId='';preview.replaceChildren();}
  workBuddySyncPreviewState();
}

function workBuddyCanPreview(){return !!workBuddyDialog?.open&&!workBuddyBusy&&!!workBuddyStatus.enabled&&!!workBuddyPlan&&String(workBuddyStatus.pending?.plan_id)===String(workBuddyPlan.plan_id);}

function workBuddyRefreshSourceState(){
  const rowId=workBuddyAssignments.get(workBuddyCurrentBugId)?.rowId||'',enabled=workBuddyCanPreview();
  $('workBuddyCaseOptions')?.querySelectorAll('input').forEach(radio=>{radio.checked=radio.value===rowId;radio.disabled=!enabled;radio.parentElement.classList.toggle('selected',radio.checked);});
  const clear=$('workBuddyClearCase');if(clear)clear.disabled=!enabled||!rowId;
  workBuddySyncPreviewState();
}

function workBuddySyncPreviewState(){
  const preview=$('workBuddyHoverPreview'),shown=preview&&!preview.hidden&&preview.dataset.bugId===workBuddyCurrentBugId?preview.dataset.rowId:'';
  $('workBuddyCaseOptions')?.querySelectorAll('input').forEach(radio=>{const displayed=!!shown&&radio.value===shown;radio.parentElement.classList.toggle('is-preview',displayed);radio.parentElement.setAttribute('aria-current',String(displayed));});
}

function workBuddyFacts(row,preview=false){
  const facts=node('div',preview?'workbuddy-hover-facts':'workbuddy-fact-grid');
  const context=node('div','workbuddy-fact-column'),results=node('div','workbuddy-fact-column');
  [['preconditions','前置条件'],['steps','复现步骤'],['actual','实际结果'],['expected','预期结果']].forEach(([field,label])=>{
    const fact=node('section','workbuddy-fact workbuddy-fact-'+field);
    fact.append(node('strong','',label),node('pre','',String(row[field]||'').trim()||(field==='preconditions'?'未提供':'待补充')));
    (field==='preconditions'||field==='steps'?context:results).append(fact);
  });
  facts.append(context,results);return facts;
}

function workBuddySourceMetadataText(sources){
  return sources.map(source=>[source.case_id,source.case_title||source.title,source.group,source.tester,source.date].map(value=>String(value||'')).join(' · ')).join('\n');
}

function workBuddyImportChanges(bug,row,mode=workBuddyReplaceContent?'replace':'fill'){
  const changes=[];
  const blocked=mode==='fill'&&workBuddySources(row).length>1&&['preconditions','steps','actual','expected'].some(field=>String(bug[field]||'').trim()&&String(row[field]||'').trim()&&bug[field]!==row[field]);
  [['preconditions','前置条件'],['steps','复现步骤'],['actual','实际结果'],['expected','预期结果']].forEach(([field,label])=>{
    const before=String(bug[field]||''),incoming=String(row[field]||'');
    if(!incoming.trim()||before===incoming)return;
    const retained=mode==='fill'&&!!before.trim();
    changes.push({label,before,after:retained?before:incoming,suggestion:incoming,retained,replaces:!retained&&!!before.trim()});
  });
  const beforeSources=Array.isArray(bug.case_sources)&&bug.case_sources.length?bug.case_sources:Object.keys(bug.case_source||{}).length?[bug.case_source]:[];
  const before=workBuddySourceMetadataText(beforeSources),after=workBuddySourceMetadataText(workBuddySources(row));
  if(before!==after)changes.push({label:'来源用例',before,after,suggestion:after,retained:false,replaces:false});
  return blocked?changes.map(change=>({...change,retained:true,replaces:false,after:change.before,blocked:true})):changes;
}

function workBuddyComparisonContent(changes){
  const content=node('div','workbuddy-comparison-content');
  changes.forEach(change=>{
    const section=node('section','workbuddy-change'+(change.retained?' retained':''));
    section.append(node('h4','',change.label+' · '+(change.retained?'保留已有内容':change.replaces?'替换':'更新')));
    const columns=node('div','workbuddy-change-columns'),before=node('div'),after=node('div');
    const proposed=change.retained?change.suggestion:change.after;
    before.append(node('strong','','导入前'),workBuddyDiffText(change.before,proposed,'del'));
    after.append(node('strong','',change.retained?'本次建议（当前模式不写入）':'导入后'),workBuddyDiffText(proposed,change.before,'mark'));
    columns.append(before,after);section.append(columns);content.append(section);
  });return content;
}

function workBuddyDiffText(value,other,tag){
  const pre=node('pre');if(!value){pre.append(node('span','','空白'));return pre;}
  const lines=value.split('\n'),comparison=other.split('\n');let start=0,end=0;
  while(start<Math.min(lines.length,comparison.length)&&lines[start]===comparison[start])++start;
  while(end<Math.min(lines.length,comparison.length)-start&&lines[lines.length-1-end]===comparison[comparison.length-1-end])++end;
  lines.forEach((line,index)=>pre.append(node(index>=start&&index<lines.length-end?tag:'span','',line+(index<lines.length-1?'\n':''))));return pre;
}

function workBuddyConfirmOverwrite(bugs){
  return new Promise(resolve=>{
    const dialog=node('dialog','modal workbuddy-compare-modal');dialog.id='workBuddyCompareDialog';dialog.setAttribute('aria-labelledby','workBuddyCompareTitle');
    const head=node('div','modal-header'),title=node('h2','','核对覆盖内容');title.id='workBuddyCompareTitle';const close=button('','icon-button',()=>dialog.close(),'close');close.setAttribute('aria-label','返回继续核对');head.append(title,close);
    const body=node('div','modal-body');body.append(node('p','muted-copy','以下显示本次将写入的变化。未提供的内容会保留，标题、公共设置、附件和提交记录不受此次导入影响。'));
    bugs.forEach(bug=>{const changes=workBuddyImportChanges(bug,workBuddyRow(bug),'replace');if(!changes.length)return;const item=node('article','workbuddy-compare-bug');item.append(node('h3','',bug.title||bug.original_title||'Bug'),workBuddyComparisonContent(changes));body.append(item);});
    let approved=false;const foot=node('div','modal-footer');foot.append(button('返回继续核对','button secondary',()=>dialog.close()),button('确认覆盖并导入','button primary',()=>{approved=true;dialog.close();}));
    dialog.append(head,body,foot);dialog.addEventListener('close',()=>{dialog.remove();resolve(approved);});document.body.append(dialog);dialog.showModal();
  });
}

function workBuddyRenderUndo(){
  const control=$('workBuddyUndo');if(!control)return;const undo=workBuddyStatus.undo;
  control.hidden=!undo?.transaction_id;control.disabled=workBuddyBusy||!undo?.available||batchBusy||!!state.job?.running;
  control.textContent='撤销上次导入'+(undo?.count?'（'+undo.count+'）':'');control.title=undo?.available?'恢复上次导入前的描述和来源；恢复后需要重新审核。':String(undo?.reason||'暂无可撤销的导入');
}

async function workBuddyUndoImport(){
  const undo=workBuddyStatus.undo;if(workBuddyBusy||batchBusy||state.job?.running||!undo?.available)return;
  if(!confirm('将恢复上次导入前的 '+undo.count+' 条 Bug 描述和来源，恢复后需要重新审核。\n'+(undo.titles||[]).join('\n')+'\n\n确认撤销？'))return;
  const serial=++workBuddySerial;$('workBuddyError').hidden=true;workBuddySetBusy(true);
  try{
    await flushSave();const result=await api('/api/workbuddy/undo',{transaction_id:undo.transaction_id});if(serial!==workBuddySerial)return;
    await replaceState(result.state);workBuddyStatus.undo=result.undo||null;workBuddyStatus.pending=null;workBuddyPlan=null;workBuddyAssignments.clear();workBuddyReplaceContent=false;workBuddyResetView();workBuddyRenderWaiting();workBuddyRenderStatus();
    toast('已撤销上次导入，恢复 '+Number(result.undone||0)+' 条 Bug · 请重新核对并审核。');
  }catch(error){workBuddyError(errorMessage(error));}
  finally{workBuddySetBusy(false);workBuddySchedulePoll();}
}

function workBuddyPreviewRow(rowId,immediate=false){
  workBuddyCaptureDetailPosition();workBuddyCancelHover();const serial=workBuddyHoverSerial,bugId=workBuddyCurrentBugId,planId=workBuddyPlan?.plan_id;
  const show=()=>{
    if(serial!==workBuddyHoverSerial||bugId!==workBuddyCurrentBugId||planId!==workBuddyPlan?.plan_id||!workBuddyCanPreview())return;
    const row=workBuddyRows().find(item=>String(item.row_id)===rowId),preview=$('workBuddyHoverPreview');if(!row||!preview)return;
    workBuddyRenderSourceSheet(row);
  };
  if(immediate)show();else workBuddyHoverTimer=setTimeout(show,100);
}

function workBuddyRestoreSelectedPreview(){
  workBuddyCancelHover();
  const row=workBuddyRow(),preview=$('workBuddyHoverPreview');
  if(!preview||!workBuddyBug())return;
  workBuddyRenderSourceSheet(row);
}

function workBuddyRenderSourceSheet(row){
  const preview=$('workBuddyHoverPreview'),bug=workBuddyBug();if(!preview||!bug)return;
  const bugId=String(bug.id),rowId=String(row?.row_id||''),chosen=!!row&&workBuddyAssignments.get(bugId)?.rowId===rowId;
  const mode=workBuddyReplaceContent?'replace':'fill';
  if(!preview.hidden&&preview.dataset.bugId===bugId&&preview.dataset.rowId===rowId&&preview.dataset.selected===String(chosen)&&preview.dataset.mode===mode){workBuddySyncPreviewState();return;}
  preview.replaceChildren();preview.hidden=false;preview.dataset.bugId=bugId;preview.dataset.rowId=rowId;preview.dataset.selected=String(chosen);preview.dataset.mode=mode;
  workBuddySyncPreviewState();
  if(!row){const empty=node('div','workbuddy-source-empty');empty.append(node('h4','','尚未选择用例'),node('p','','悬停查看内容，点击选用。'));preview.append(empty);preview.scrollTop=0;return;}
  const heading=node('header','workbuddy-hover-heading'),identity=node('div');
  const grouped=workBuddySources(row).length>1;
  identity.append(node('span','workbuddy-preview-kicker',grouped?workBuddySourceLabel(row)+' · '+(chosen?'当前建议':'悬停预览 · 尚未选用'):(chosen?'当前用例':'悬停预览 · 尚未选用')),node('h4','',[row.case_id,row.title||'未提供用例名称'].filter(Boolean).join(' ')));
  if(chosen)heading.append(identity,node('span','workbuddy-current-source','已选用'));
  else heading.append(identity,button(grouped?'选用此整理建议':'选用此用例','button secondary',()=>workBuddyChooseRow(rowId)));
  preview.append(heading);
  const notes=Array.from(new Set([...(row.review_notes||[]),...(row.warnings||[])].map(String).filter(text=>text.trim())));
  if(notes.length){const notice=node('details','workbuddy-review-notes');notice.id='workBuddyReviewNotes';notice.append(node('summary','','待确认 · '+notes.length+' 项'));const list=node('ul');notes.forEach(text=>list.append(node('li','',text)));notice.append(list);preview.append(notice);}
  preview.append(workBuddyFacts(row,true));
  if(chosen){const changes=workBuddyImportChanges(bug,row,mode);if(changes.length){const comparison=node('details','workbuddy-evidence workbuddy-comparison');comparison.id='workBuddyComparison';comparison.open=mode==='replace'&&changes.some(change=>change.replaces);comparison.append(node('summary','','导入前后对比 · '+(changes.some(change=>change.blocked)?'当前模式无法导入':changes.filter(change=>!change.retained).length+' 项变化')),workBuddyComparisonContent(changes));preview.append(comparison);}}
  if(row.source_cases?.length){
    const sources=node('details','workbuddy-evidence workbuddy-source-cases');sources.id='workBuddySourceCases';sources.append(node('summary','','来源用例（'+row.source_cases.length+' 条）'));
    row.source_cases.forEach((source,index)=>{
      const entry=node('article','workbuddy-source-case');entry.append(node('h5','',[String(index+1)+'.',source.case_id,source.title||'未提供用例名称'].filter(Boolean).join(' ')));
      const metadata=[source.group,source.tester,source.date].filter(Boolean);if(metadata.length)entry.append(node('p','workbuddy-row-meta',metadata.join(' · ')));
      entry.append(workBuddyFacts(source,true));
      if(source.source_actual&&source.source_actual!==source.actual)entry.append(node('strong','','原始失败备注'),node('pre','workbuddy-source-actual',String(source.source_actual)));
      sources.append(entry);
    });preview.append(sources);
  }
  const evidence=node('details','workbuddy-evidence');evidence.id='workBuddyEvidence';evidence.append(node('summary','','原始信息'));
  const reason=workBuddyRank(row,bug)>0?String(row.match_reason||'请核对用例中的失败现象与当前 Bug 是否一致。'):'手动选择的用例，请结合 Bug 和附件核对。';
  evidence.append(node('p','workbuddy-match-reason',reason));
  const meta=[row.group,row.tester,row.date].filter(Boolean);if(meta.length)evidence.append(node('p','workbuddy-row-meta',meta.join(' · ')));
  evidence.append(node('p','workbuddy-row-meta','完整 Bug 标题：'+workBuddyTitleParts(bug).full));
  if(bug.original_title)evidence.append(node('p','workbuddy-row-meta','附件文件夹：'+bug.original_title));
  const attachments=(bug.attachments||[]).map(item=>item.name).filter(Boolean);if(attachments.length)evidence.append(node('p','workbuddy-row-meta','附件：'+attachments.join('、')));
  if(row.source_actual)evidence.append(node('strong','','原始失败备注'),node('pre','workbuddy-source-actual',String(row.source_actual)));
  preview.append(evidence);
  const existing=['preconditions','steps','actual','expected'].filter(field=>String(bug[field]||'').trim()).length;
  const conflicts=grouped&&['preconditions','steps','actual','expected'].some(field=>String(row[field]||'').trim()&&String(bug[field]||'').trim()&&row[field]!==bug[field]);
  if(chosen&&existing)preview.append(node('p','workbuddy-existing-hint',mode==='replace'?'已选择覆盖已有内容。导入前会汇总显示变化，请核对后确认。':conflicts?'合并报告与已有内容不同。请核对后勾选下方「覆盖已有内容」，再导入完整报告。':'已有 '+existing+' 项内容，默认只补空白。'));
  preview.scrollTop=chosen?(workBuddyDetailPositions.get(bugId)||0):0;
}

function workBuddyRenderDetail(){
  workBuddyClearHover();const area=$('workBuddyDetail');if(!area)return;area.replaceChildren();
  const bug=workBuddyBug(),visible=workBuddyVisibleBugs(),index=visible.findIndex(item=>String(item.id)===workBuddyCurrentBugId);
  if(!bug){const empty=node('div','workbuddy-detail-empty');empty.append(node('h3','','选择左侧 Bug 开始核对'),node('p','','调整搜索或筛选后，可以继续核对其他 Bug。'));area.append(empty);return;}
  const id=String(bug.id),selection=workBuddyAssignments.get(id),row=workBuddyRow(bug),parts=workBuddyTitleParts(bug);
  const top=node('div','workbuddy-detail-top'),heading=node('div','workbuddy-detail-heading');
  heading.append(node('span','workbuddy-position','Bug '+(index+1)+' / '+visible.length),node('h3','',parts.full));
  const nav=node('div','workbuddy-detail-navigation'),previous=button('上一个','button secondary',()=>workBuddyNavigate(-1),'left'),next=button('下一个','button secondary',()=>workBuddyNavigate(1),'right');previous.id='workBuddyPrevious';next.id='workBuddyNext';nav.append(previous,next);top.append(heading,nav);
  const stage=node('div','workbuddy-detail-stage');stage.id='workBuddyDetailStage';
  const layer=node('div','workbuddy-picker workbuddy-picker-layer');layer.id='workBuddyPickerLayer';
  const candidatesPanel=node('div','workbuddy-candidates-panel'),pickerHeading=node('div','workbuddy-picker-heading');
  pickerHeading.append(node('strong','','整理建议'));
  const search=node('input','workbuddy-case-search');search.id='workBuddyCaseSearch';search.type='search';search.placeholder='搜索用例 ID、名称或失败现象';search.setAttribute('aria-label','搜索可选失败用例');search.value=workBuddyCaseQueries.get(id)||'';
  const caption=node('div','workbuddy-list-caption');caption.id='workBuddyCaseCaption';
  const options=node('div','workbuddy-case-options');options.id='workBuddyCaseOptions';options.setAttribute('role','radiogroup');options.setAttribute('aria-label','这个 Bug 的整理建议');
  const populate=()=>{
    workBuddyCancelHover();const candidates=workBuddyCandidateRows(bug,search.value);
    caption.textContent=candidates.length+' 份 · 悬停预览，点击选用';options.replaceChildren();
    if(!candidates.length)options.append(node('div','workbuddy-list-empty','没有找到用例，试试用例 ID 或失败现象。'));
    candidates.forEach(item=>{
      const rowId=String(item.row_id),label=node('label','workbuddy-case-option');label.dataset.rowId=rowId;label.classList.toggle('selected',selection.rowId===rowId);
      const radio=node('input');radio.type='radio';radio.name='workBuddyCaseChoice';radio.value=rowId;radio.tabIndex=0;radio.checked=selection.rowId===rowId;radio.setAttribute('aria-label','选择整理建议 '+workBuddySourceLabel(item)+' '+String(item.title||''));radio.addEventListener('change',()=>{if(radio.checked)workBuddyChooseRow(rowId);});
      label.addEventListener('pointerenter',()=>workBuddyPreviewRow(rowId));label.addEventListener('focusin',()=>workBuddyPreviewRow(rowId,true));
      label.addEventListener('click',()=>{if(selection.rowId===rowId)workBuddyRestoreSelectedPreview();});
      radio.addEventListener('keydown',event=>{
        if(event.key==='Enter'||event.key===' '){event.preventDefault();workBuddyChooseRow(rowId);}
        else if(['ArrowDown','ArrowUp','ArrowRight','ArrowLeft','Home','End'].includes(event.key)){event.preventDefault();const controls=Array.from(options.querySelectorAll('input')),position=controls.indexOf(radio),direction=['ArrowDown','ArrowRight'].includes(event.key)?1:-1;controls[event.key==='Home'?0:event.key==='End'?controls.length-1:(position+direction+controls.length)%controls.length]?.focus();}
      });
      const content=node('span','workbuddy-option-content'),identity=node('span','workbuddy-option-heading');identity.append(node('strong','',workBuddySourceLabel(item)));
      const rank=workBuddyRank(item,bug);if(rank)identity.append(node('span','workbuddy-match-tag '+(rank===3?'exact':'suggested'),rank===3?'ID 一致':'推荐'));
      content.append(identity,node('span','workbuddy-option-title',item.title||'未提供用例名称'));
      label.append(radio,content);options.append(label);
    });
    workBuddyRestoreSelectedPreview();
  };
  search.addEventListener('input',()=>{workBuddyCaseQueries.set(id,search.value);populate();});search.addEventListener('focus',workBuddyRestoreSelectedPreview);
  const clear=button('暂不匹配','text-button',()=>workBuddyChooseRow(''));clear.id='workBuddyClearCase';clear.disabled=!row;
  candidatesPanel.append(pickerHeading,search,caption,options,clear);
  const hover=node('section','workbuddy-hover-preview');hover.id='workBuddyHoverPreview';hover.hidden=true;hover.tabIndex=0;hover.setAttribute('aria-label','候选用例内容预览');
  layer.append(candidatesPanel,hover);layer.addEventListener('pointerleave',workBuddyRestoreSelectedPreview);
  const checkLabel=node('label','workbuddy-detail-check'),check=node('input');check.id='workBuddyDetailCheck';check.type='checkbox';check.checked=selection.checked;check.disabled=!row;
  check.addEventListener('focus',workBuddyRestoreSelectedPreview);check.addEventListener('change',()=>{workBuddyRestoreSelectedPreview();selection.checked=!!workBuddyRow(bug)&&check.checked;workBuddySelectionChanged();});checkLabel.append(check,node('span','','本条已核对'));
  stage.append(layer);area.append(top,stage,checkLabel);populate();workBuddyRestoreSelectedPreview();workBuddyRefreshNavigation();
}

function workBuddySelected(){return workBuddyBugs().filter(bug=>workBuddyAssignments.get(String(bug.id))?.checked);}

function workBuddyUpdateFooter(){
  if(!workBuddyDialog)return;
  workBuddyRenderUndo();
  const apply=$('workBuddyApply');apply.hidden=!workBuddyPlan;
  const policy=$('workBuddyReplaceLabel');if(policy)policy.hidden=!workBuddyPlan;const replace=$('workBuddyReplace');if(replace)replace.checked=workBuddyReplaceContent;
  if(!workBuddyPlan){apply.disabled=true;return;}
  const bugs=workBuddySelected(),missing=bugs.some(bug=>!workBuddyRow(bug));
  const detailCheck=$('workBuddyDetailCheck'),clear=$('workBuddyClearCase');if(detailCheck)detailCheck.disabled=workBuddyBusy||!workBuddyRow();if(clear)clear.disabled=workBuddyBusy||!workBuddyRow();
  workBuddyRefreshSourceState();
  const pending=workBuddyStatus.pending,stale=!pending||String(pending.plan_id)!==String(workBuddyPlan.plan_id);
  apply.replaceChildren(icon('check'),node('span','','导入已核对 Bug（'+bugs.length+'）'));
  apply.disabled=workBuddyBusy||!workBuddyStatus.enabled||!bugs.length||missing||stale;
  const remaining=workBuddyBugs(),associated=remaining.filter(bug=>!!workBuddyRow(bug)).length,completed=(workBuddyPlan.completed_bug_ids||[]).length;
  const total=Number(workBuddyPlan.total_bugs)||remaining.length+completed;
  const summary=$('workBuddySummary');if(summary){summary.replaceChildren(node('strong','','本批次 '+total+' 个 Bug'),node('span','','已核对 '+bugs.length+' 个'));
    if(remaining.length-associated)summary.append(node('span','','待匹配 '+(remaining.length-associated)+' 个'));
    if(completed)summary.append(node('span','','已导入 '+completed+' 个'));
    const sourceCount=workBuddyRows().reduce((total,row)=>total+workBuddySources(row).length,0);
    summary.title='已匹配 '+associated+' 个 Bug · 收到 '+sourceCount+' 条用例'+(sourceCount!==workBuddyRows().length?' · '+workBuddyRows().length+' 份整理建议':'');
    if(missing)summary.append(node('span','workbuddy-summary-warning','勾选的 Bug 还没有选择用例，请先选择对应的失败用例。'));
    if(!workBuddyStatus.enabled)summary.append(node('span','workbuddy-summary-warning','连接已关闭或到期，请重新开启后再整理。'));
  }
}

async function workBuddyApply(){
  if(workBuddyBusy||!workBuddyPlan)return;
  if(batchBusy||scanBusy||state.job?.running){workBuddyError('请等当前操作完成，再导入整理建议。');return;}
  if(!workBuddyStatus.enabled||!workBuddyStatus.pending||String(workBuddyStatus.pending.plan_id)!==String(workBuddyPlan.plan_id)){workBuddyError('这份建议或连接已失效，请重新加载建议，或开启连接后再整理。');return;}
  const bugs=workBuddySelected();
  if(!bugs.length||bugs.some(bug=>!workBuddyRow(bug))){workBuddyError('请先为已勾选的 Bug 选择对应的失败用例。');return;}
  const mode=workBuddyReplaceContent?'replace':'fill',planId=workBuddyPlan.plan_id,serial=++workBuddySerial;
  const assignments=bugs.map(bug=>({row_id:workBuddyAssignments.get(String(bug.id)).rowId,bug_id:String(bug.id),mode}));
  $('workBuddyError').hidden=true;workBuddySetBusy(true);
  try{
    if(mode==='replace'&&bugs.some(bug=>workBuddyImportChanges(bug,workBuddyRow(bug),mode).some(change=>change.replaces))){if(!await workBuddyConfirmOverwrite(bugs))return;}
    await flushSave();const result=await api('/api/workbuddy/apply',{plan_id:planId,review_scope:'bugs',assignments});if(serial!==workBuddySerial)return;
    await replaceState(result.state);
    workBuddyStatus.undo=result.undo||workBuddyStatus.undo||null;
    const previousAssignments=workBuddyAssignments;
    workBuddyPlan=result.pending||null;workBuddyStatus.pending=workBuddyPlan;
    if(workBuddyPlan){workBuddyInitializePlan(previousAssignments);workBuddyRenderPlan();}
    else{workBuddyAssignments=new Map();workBuddyReplaceContent=false;workBuddyResetView();workBuddyRenderWaiting();}
    const count=Array.isArray(result.applied)?result.applied.length:Number(result.applied||0),unchanged=Array.isArray(result.unchanged)?result.unchanged.length:Number(result.unchanged||0);
    const skipped=Array.isArray(result.skipped_fields)?result.skipped_fields.length:Number(result.skipped_fields||0);
    const remaining=Number.isInteger(result.remaining_bugs)?result.remaining_bugs:(workBuddyPlan?.bugs||[]).length;
    toast((count?'已导入 '+count+' 个 Bug':unchanged?'已处理 '+unchanged+' 个已有草稿':'Bug 整理建议已处理')+'，剩余 '+remaining+' 个 Bug 待整理'+(skipped?' · 保留了 '+skipped+' 项已有内容':'')+' · 请核对实际结果和附件，再审核。');
    workBuddyRenderStatus();
  }catch(error){if(serial===workBuddySerial)workBuddyError(errorMessage(error)+' 草稿变化后，请重新让 WorkBuddy 整理并核对。');}
  finally{if(serial===workBuddySerial){workBuddySetBusy(false);workBuddySchedulePoll();}}
}
