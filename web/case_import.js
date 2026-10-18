/* Clipboard import stays local; clipboard HTML is sent to the parser, never rendered. */
"use strict";

let caseImportDialog = null;
let caseImportPreview = null;
let caseImportHtml = '';
let caseImportText = '';
let caseImportBusy = false;
let caseImportSerial = 0;
let caseImportMappingDirty = false;
let caseImportAssignments = new Map();
const CASE_IMPORT_FIELDS = [
  ['case_id','用例 ID'], ['title','用例名称'], ['group','用例分组'],
  ['preconditions','前置条件'], ['steps','复现步骤'], ['expected','预期结果'],
  ['actual','实际结果 / 备注'], ['tester','测试人员'], ['date','测试时间'], ['result','测试结果']
];

function installCaseImport() {
  const trigger = $('casePasteButton');
  if (trigger && !trigger.dataset.caseImportBound) {
    trigger.dataset.caseImportBound = 'true';
    trigger.addEventListener('click', openCaseImport);
  }
  if (caseImportDialog) return;
  const dialog = node('dialog','modal case-import-modal');
  dialog.id = 'caseImportDialog';
  dialog.setAttribute('aria-labelledby','caseImportTitle');
  const head = node('div','modal-header');
  const heading = node('div');
  heading.append(node('span','eyebrow','从共享表格，一次带入多条用例'));
  const title = node('h2','','粘贴测试用例'); title.id = 'caseImportTitle';
  heading.append(title);
  const close = button('','icon-button',()=>dialog.close(),'close');
  close.setAttribute('aria-label','关闭用例导入'); close.id = 'caseImportClose';
  head.append(heading,close);
  const body = node('div','modal-body case-import-body'); body.id = 'caseImportBody';
  const foot = node('div','modal-footer case-import-footer');
  const hint = node('span','footer-hint'); hint.id = 'caseImportHint';
  const back = button('重新粘贴','button secondary',caseImportShowInput); back.id = 'caseImportBack'; back.hidden = true;
  const cancel = button('取消','button secondary',()=>dialog.close()); cancel.id = 'caseImportCancel';
  const primary = button('识别用例','button primary',caseImportMainAction,'layers'); primary.id = 'caseImportPrimary';
  foot.append(hint,back,cancel,primary);
  dialog.append(head,body,foot); document.body.append(dialog); caseImportDialog = dialog;
  dialog.addEventListener('cancel',event=>{if(caseImportBusy)event.preventDefault();});
  dialog.addEventListener('close',()=>{
    ++caseImportSerial; caseImportPreview = null; caseImportAssignments.clear();
    caseImportHtml = ''; caseImportText = ''; caseImportMappingDirty = false;
    body.replaceChildren();
  });
}

async function openCaseImport() {
  if (batchBusy || scanBusy || state.job?.running) {toast('请等当前操作完成，再导入用例。',true);return;}
  if (!state.bugs?.length) {toast('先扫描今天的附件文件夹，再粘贴用例与 Bug 关联。');return;}
  installCaseImport();
  if (caseImportDialog.open) return;
  try {
    await flushSave();
    if (batchBusy || scanBusy || state.job?.running) return;
    caseImportPreview = null; caseImportAssignments.clear(); caseImportHtml = ''; caseImportText = '';
    caseImportBusy = false; caseImportMappingDirty = false;
    caseImportShowInput(); caseImportSetBusy(false); caseImportDialog.showModal(); $('caseImportInput').focus();
  } catch(error) {toast(errorMessage(error),true);}
}

function caseImportSetBusy(value) {
  caseImportBusy = value;
  if (!caseImportDialog) return;
  caseImportDialog.setAttribute('aria-busy',String(value));
  caseImportDialog.querySelectorAll('input,textarea,select,button').forEach(control=>{control.disabled=value;});
  if(!value){
    const filter=$('caseImportOnlyFailures'),result=caseImportPreview?.mapping?.result;
    if(filter)filter.disabled=result===null||result===undefined;
    caseImportUpdateFooter();
  }
}

function caseImportShowInput() {
  if(caseImportBusy)return;
  ++caseImportSerial; caseImportPreview = null; caseImportAssignments.clear(); caseImportMappingDirty = false;
  const body = $('caseImportBody'); body.replaceChildren();
  const intro = node('div','case-import-intro');
  intro.append(icon('copy'),node('div','','在共享表格中选中多条用例，复制后粘贴到下面。可以带表头；单元格里的多行步骤会保留。'));
  const label = node('label','field case-import-input-label');
  label.append(node('span','','粘贴用例内容'));
  const input = node('textarea','case-import-input'); input.id = 'caseImportInput'; input.spellcheck = false;
  input.placeholder = '在这里按 Ctrl + V，一次粘贴多行用例。\n\n前置条件、复现步骤、预期结果会直接带入；备注作为实际结果供你核对。';
  input.value = caseImportText;
  input.addEventListener('paste',event=>{
    const transfer = event.clipboardData; if(!transfer)return;
    const plain = transfer.getData('text/plain');
    if(!plain)return;
    event.preventDefault();
    const entire = input.selectionStart===0 && input.selectionEnd===input.value.length;
    input.setRangeText(plain,input.selectionStart,input.selectionEnd,'end');
    caseImportText=input.value; caseImportHtml=entire?transfer.getData('text/html'):'';
    caseImportUpdateFooter();
  });
  input.addEventListener('input',()=>{caseImportText=input.value;caseImportHtml='';caseImportUpdateFooter();});
  label.append(input);
  const note=node('p','case-import-local-note'); note.append(icon('lock'),node('span','','粘贴内容只在本机处理；导入后仍需审核，再提交到禅道。'));
  const error = node('div','notice warning case-import-error'); error.id = 'caseImportError'; error.hidden=true; error.setAttribute('role','alert');
  body.append(intro,label,note,error);
  $('caseImportBack').hidden=true;
  $('caseImportPrimary').replaceChildren(icon('layers'),node('span','','识别用例'));
  $('caseImportHint').textContent='1 · 粘贴用例';
  caseImportUpdateFooter();
}

function caseImportError(message) {
  const box=$('caseImportError'); if(!box){toast(message,true);return;}
  box.textContent=message; box.hidden=false;
}

async function caseImportMainAction() {
  if(caseImportBusy)return;
  if(caseImportPreview && !caseImportMappingDirty) await caseImportApply();
  else await caseImportRecognize(!!caseImportPreview);
}

function caseImportSource() {return {text:caseImportText,...(caseImportHtml?{html:caseImportHtml}:{})};}

async function caseImportRecognize(manual=false) {
  if(caseImportBusy)return;
  if(!caseImportText.trim()&&!caseImportHtml){caseImportError('先粘贴共享表格里的用例内容。');return;}
  const request=caseImportSource();
  if(manual && caseImportPreview){
    request.mapping={};
    CASE_IMPORT_FIELDS.forEach(([field])=>{
      const value=$('caseImportMap-'+field)?.value;
      request.mapping[field]=value===''||value===undefined?null:Number(value);
    });
    request.has_header=!!$('caseImportHasHeader')?.checked;
  }
  const serial=++caseImportSerial;
  $('caseImportError').hidden=true; caseImportSetBusy(true);
  $('caseImportPrimary').replaceChildren(node('span','','正在识别…'));
  try {
    const result=await api('/api/cases/preview',request);
    if(serial!==caseImportSerial || !caseImportDialog.open)return;
    caseImportPreview=result; caseImportMappingDirty=false; caseImportAssignments.clear();
    const candidates = new Set((result.bugs||[]).filter(caseImportCanTarget).map(bug=>String(bug.id)));
    (result.rows||[]).forEach(row=>{
      const suggested=String(row.suggested_bug_id||'');
      const hasResult=result.mapping?.result!==null&&result.mapping?.result!==undefined;
      caseImportAssignments.set(String(row.row_id),{checked:!hasResult||caseImportIsFailure(row.result),bugId:candidates.has(suggested)?suggested:''});
    });
    caseImportRenderPreview();
  } catch(error) {if(serial===caseImportSerial)caseImportError(errorMessage(error));}
  finally {if(serial===caseImportSerial){caseImportSetBusy(false);if(!caseImportPreview)$('caseImportPrimary').replaceChildren(icon('layers'),node('span','','识别用例'));}}
}

function caseImportCanTarget(bug) {return !bug.remote_id && !['submitted','submitting','uncertain','partial'].includes(bug.status);}
function caseImportIsFailure(result) {return /^(失败|不通过|未通过|fail(?:ed)?|ng)$/i.test(String(result||'').trim());}

function caseImportRenderPreview() {
  const data=caseImportPreview, body=$('caseImportBody'); body.replaceChildren();
  const summary=node('div','case-import-summary'); summary.id='caseImportSummary'; summary.setAttribute('role','status');
  const intro=node('p','case-import-preview-intro','为用例选对应的附件文件夹。只有已勾选且已关联的用例会导入；重复的用例名称不会按顺序匹配。');
  const warnings=node('div','notice warning case-import-warnings');
  const messages=(data.warnings||[]).map(String);
  if(messages.length)warnings.append(node('div','',messages.join('\n')));
  warnings.hidden=!messages.length;
  const error=node('div','notice warning case-import-error');error.id='caseImportError';error.hidden=true;error.setAttribute('role','alert');
  const mapping=caseImportMappingPanel(data);
  const tools=node('div','case-import-tools');
  const filterLabel=node('label','case-import-check');
  const onlyFailures=node('input');onlyFailures.id='caseImportOnlyFailures';onlyFailures.type='checkbox';
  onlyFailures.checked=data.mapping?.result!==null&&data.mapping?.result!==undefined;
  onlyFailures.disabled=!(data.mapping?.result!==null&&data.mapping?.result!==undefined);
  filterLabel.append(onlyFailures,node('span','','仅显示失败用例'));
  onlyFailures.addEventListener('change',caseImportRenderRows);
  tools.append(filterLabel,button('勾选已关联用例','text-button',()=>{
    caseImportVisibleRows().forEach(row=>{const item=caseImportAssignments.get(String(row.row_id));if(item)item.checked=!!item.bugId;});
    caseImportRenderRows();
  }));
  const list=node('div','case-import-rows');list.id='caseImportRows';
  const policy=node('div','case-import-policy');
  const replaceLabel=node('label','case-import-check');
  const replace=node('input');replace.type='checkbox';replace.id='caseImportReplace';
  replaceLabel.append(replace,node('span','','覆盖已有的这四项内容（需要重新审核）'));
  policy.append(replaceLabel,node('p','','默认只填空白项，保留你写过的内容。导入前请核对备注中的实际现象，备注不一定是完整的实际结果。'));
  body.append(summary,intro,warnings,mapping,tools,list,policy,error);
  $('caseImportBack').hidden=false;
  $('caseImportHint').textContent='2 · 关联并导入';
  caseImportRenderRows();
}

function caseImportMappingPanel(data) {
  const panel=node('details','case-import-mapping'); panel.append(node('summary','','字段对应 · 识别不准确时调整'));
  const copy=node('p','','核对这些列来自哪里。修改后点击“重新识别”，再关联要导入的 Bug。');
  const headerLabel=node('label','case-import-check');const header=node('input');header.type='checkbox';header.id='caseImportHasHeader';header.checked=!!data.has_header;
  headerLabel.append(header,node('span','','首行是表头'));header.addEventListener('change',caseImportMappingChanged);
  const grid=node('div','case-import-mapping-grid');
  CASE_IMPORT_FIELDS.forEach(([field,label])=>{
    const row=node('label','case-import-map-field');row.append(node('span','',label+(field==='steps'||field==='expected'?' *':'')));
    const select=node('select');select.id='caseImportMap-'+field;
    const none=node('option','','不导入此项');none.value='';select.append(none);
    (data.columns||[]).forEach(column=>{
      const caption='第 '+(Number(column.index)+1)+' 列'+(column.label?' · '+column.label:'');
      const option=node('option','',caption);option.value=String(column.index);option.title=String(column.sample||'');select.append(option);
    });
    const value=data.mapping?.[field];select.value=value===undefined||value===null?'':String(value);
    select.addEventListener('change',caseImportMappingChanged);row.append(select);grid.append(row);
  });
  panel.append(copy,headerLabel,grid,button('重新识别','button secondary',()=>caseImportRecognize(true),'refresh'));
  if(data.mapping?.steps===undefined||data.mapping?.steps===null||data.mapping?.expected===undefined||data.mapping?.expected===null)panel.open=true;
  return panel;
}

function caseImportMappingChanged() {
  caseImportMappingDirty=true;
  const message=$('caseImportError');message.hidden=false;message.textContent='字段对应已修改，请先重新识别，再关联和导入。';
  caseImportUpdateFooter();
}

function caseImportVisibleRows() {
  const rows=caseImportPreview?.rows||[];
  return $('caseImportOnlyFailures')?.checked?rows.filter(row=>caseImportIsFailure(row.result)):rows;
}

function caseImportRenderRows() {
  const list=$('caseImportRows');if(!list)return;list.replaceChildren();
  const rows=caseImportVisibleRows(), bugs=(caseImportPreview.bugs||[]).filter(caseImportCanTarget);
  const shown=rows.slice(0,300);
  if(!shown.length)list.append(node('div','case-import-empty','当前没有失败用例。可以取消“仅显示失败用例”，检查识别结果。'));
  shown.forEach(row=>{
    const id=String(row.row_id),selection=caseImportAssignments.get(id)||{checked:false,bugId:''};
    const card=node('article','case-import-row');card.dataset.rowId=id;
    const top=node('div','case-import-row-heading');
    const check=node('input');check.type='checkbox';check.checked=selection.checked;check.setAttribute('aria-label','选择用例 '+(row.case_id||row.source_row));
    check.addEventListener('change',()=>{selection.checked=check.checked;caseImportUpdateFooter();});
    const heading=node('div','case-import-row-title');
    const identity=node('div','case-import-row-identity');identity.append(node('strong','',row.case_id||'第 '+row.source_row+' 条用例'));
    if(row.result)identity.append(node('span','case-import-result'+(caseImportIsFailure(row.result)?' failure':''),row.result));
    heading.append(identity,node('h3','',row.title||'未识别到用例名称'));
    const meta=[row.group,row.tester,row.date].filter(Boolean);if(meta.length)heading.append(node('p','case-import-row-meta',meta.join(' · ')));
    top.append(check,heading);card.append(top);
    const target=node('label','case-import-target');target.append(node('span','','关联 Bug / 附件文件夹'));
    const select=node('select');select.setAttribute('aria-label','用例 '+(row.case_id||row.source_row)+' 关联的 Bug');
    const blank=node('option','','请选择对应 Bug（不会按顺序猜）');blank.value='';select.append(blank);
    bugs.forEach(bug=>{
      const full=String(bug.original_title||bug.title||'Bug');
      const option=node('option','',full.length>110?full.slice(0,107)+'…':full);option.title=full;option.value=String(bug.id);select.append(option);
    });
    select.value=selection.bugId;
    const match=node('small','case-import-match');
    const updateMatch=()=>{
      const bug=bugs.find(item=>String(item.id)===selection.bugId);
      const existing=bug?['preconditions','steps','expected','actual'].filter(field=>String(bug[field]||'').trim()).length:0;
      if(!bug)match.textContent='未关联，暂不导入这条用例。';
      else if(selection.bugId===String(row.suggested_bug_id||'')&&row.match_reason)match.textContent=String(row.match_reason)+(existing?' · 已有 '+existing+' 项内容，默认保留':'');
      else match.textContent='已选择附件文件夹'+(existing?' · 已有 '+existing+' 项内容，默认保留':'');
    };
    select.addEventListener('change',()=>{selection.bugId=select.value;updateMatch();caseImportUpdateFooter();});
    target.append(select,match);updateMatch();card.append(target);
    const facts=node('details','case-import-facts');facts.append(node('summary','','查看将导入的内容'));
    [['preconditions','前置条件'],['steps','复现步骤'],['expected','预期结果'],['actual','实际结果 / 备注（请核对）']].forEach(([field,label])=>{
      const part=node('div','case-import-fact');part.append(node('strong','',label),node('pre','',String(row[field]||'').trim()||'空白 · 需要时补充'));facts.append(part);
    });
    card.append(facts);
    if(row.warnings?.length)card.append(node('p','case-import-row-warning',row.warnings.map(String).join('；')));
    list.append(card);
  });
  if(rows.length>300)list.append(node('div','notice warning','本次识别 '+rows.length+' 条，仅显示前 300 条。建议分批粘贴，便于核对附件。'));
  caseImportUpdateFooter();
}

function caseImportSelected() {
  return caseImportVisibleRows().slice(0,300).filter(row=>{
    const selected=caseImportAssignments.get(String(row.row_id));return selected?.checked&&selected.bugId;
  });
}

function caseImportUpdateFooter() {
  const primary=$('caseImportPrimary');if(!primary || caseImportBusy)return;
  if(!caseImportPreview){primary.disabled=!caseImportText.trim()&&!caseImportHtml;return;}
  if(caseImportMappingDirty){primary.replaceChildren(icon('refresh'),node('span','','重新识别'));primary.disabled=false;return;}
  const rows=caseImportSelected();const targetIds=rows.map(row=>caseImportAssignments.get(String(row.row_id)).bugId);
  const duplicate=targetIds.length!==new Set(targetIds).size;
  const mapped=caseImportPreview.mapping||{};
  const required=mapped.steps!==null&&mapped.steps!==undefined&&mapped.expected!==null&&mapped.expected!==undefined;
  primary.replaceChildren(icon('check'),node('span','','导入已关联用例（'+rows.length+'）'));
  primary.disabled=!rows.length||duplicate||!required;
  const summary=$('caseImportSummary');
  if(summary){
    const all=caseImportPreview.rows||[],failures=all.filter(row=>caseImportIsFailure(row.result)).length;
    summary.replaceChildren(node('strong','','识别 '+all.length+' 条用例'),node('span','',failures+' 条失败'),node('span','',rows.length+' 条已勾选并关联'));
    if(duplicate)summary.append(node('span','case-import-summary-warning','同一个 Bug 只能关联一条用例，请调整选择。'));
    if(!required)summary.append(node('span','case-import-summary-warning','请在“字段对应”中选择复现步骤和预期结果列。'));
  }
}

async function caseImportApply() {
  if(caseImportBusy||!caseImportPreview||caseImportMappingDirty)return;
  if(batchBusy||scanBusy||state.job?.running){caseImportError('请等当前操作完成，再导入用例。');return;}
  const rows=caseImportSelected();if(!rows.length){caseImportError('先为要导入的用例选择对应 Bug，并勾选这条用例。');return;}
  const targets=new Set(),bugs=new Map((caseImportPreview.bugs||[]).map(bug=>[String(bug.id),bug]));
  const mode=$('caseImportReplace').checked?'replace':'fill';
  const assignments=[];
  for(const row of rows){
    const bugId=caseImportAssignments.get(String(row.row_id)).bugId,bug=bugs.get(bugId);
    if(targets.has(bugId)){caseImportError('同一个 Bug 关联了多条用例，请调整选择后再导入。');return;}
    if(!bug||!caseImportCanTarget(bug)){caseImportError('有一条关联的 Bug 目前不能修改，请重新识别。');return;}
    targets.add(bugId);assignments.push({row_id:row.row_id,bug_id:bugId,review_token:String(bug.review_token||''),mode});
  }
  const request={...caseImportSource(),mapping:caseImportPreview.mapping,has_header:!!caseImportPreview.has_header,batch_key:caseImportPreview.batch_key,assignments};
  const serial=++caseImportSerial;$('caseImportError').hidden=true;caseImportSetBusy(true);
  $('caseImportPrimary').replaceChildren(node('span','','正在导入…'));
  try {
    await flushSave();
    const result=await api('/api/cases/apply',request);
    if(serial!==caseImportSerial)return;
    await replaceState(result.state);
    caseImportSetBusy(false);caseImportDialog.close();
    const count=Array.isArray(result.applied)?result.applied.length:Number(result.applied||0);
    const unchanged=Array.isArray(result.unchanged)?result.unchanged.length:Number(result.unchanged||0);
    const skipped=Array.isArray(result.skipped_fields)?result.skipped_fields.length:Number(result.skipped_fields||0);
    const retained=skipped?' · 保留了 '+skipped+' 项已有内容':'';
    const message=count?'已导入 '+count+' 条用例'+retained+' · 请核对实际结果和附件，再审核。':unchanged?'内容相同或已有内容，保留了 '+unchanged+' 条草稿'+retained+'。':'用例关联已保存'+retained+'，请核对草稿内容。';
    toast(message);
  } catch(error) {
    if(serial!==caseImportSerial)return;
    caseImportError(errorMessage(error)+' 如草稿已发生变化，请点击“重新粘贴”后再识别。');
  } finally {if(serial===caseImportSerial)caseImportSetBusy(false);}
}
