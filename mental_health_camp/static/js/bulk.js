(() => {
const root=document.getElementById('bulk-controls'); if(!root)return;
const summary=document.getElementById('bulk-summary'), confirm=document.getElementById('bulk-confirm');let token=null,requestId=null;
function reset(){token=null;requestId=null;confirm.hidden=true;}
document.getElementById('bulk-all').onchange=e=>{document.querySelectorAll('.bulk-item').forEach(x=>x.checked=e.target.checked);reset();};
document.addEventListener('change',e=>{if(e.target.matches('.bulk-item,#bulk-reviewer,#bulk-action'))reset();});
async function post(path,data){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','x-csrf-token':document.getElementById('bulk-csrf').value},body:JSON.stringify(data)});const body=await r.json();if(!r.ok)throw new Error(JSON.stringify(body.detail));return body;}
document.getElementById('bulk-preview').onclick=async()=>{reset();try{const ids=[...document.querySelectorAll('.bulk-item:checked')].map(x=>Number(x.value));const reviewer=document.getElementById('bulk-reviewer');const data=await post('/admin/bulk/preview',{action:document.getElementById('bulk-action').value,ids,reviewer_id:reviewer?Number(reviewer.value):null});token=data.token;requestId=data.request_id;summary.textContent='共 '+data.count+' 条；接收审核员 '+(data.reviewer_id||'不适用')+'；容量变化 '+JSON.stringify(data.capacity||'不适用')+'。有效期10分钟。\n'+JSON.stringify(data.records,null,2);confirm.hidden=false;}catch(e){summary.textContent=e.message;}};
confirm.onclick=async()=>{confirm.disabled=true;try{const result=await post('/admin/bulk/execute',{token,request_id:requestId});summary.textContent='完成 '+result.count+' 条，批次 '+result.operation_id;reset();document.querySelectorAll('.bulk-item:checked').forEach(x=>{x.checked=false;x.disabled=true;});}catch(e){summary.textContent=e.message;}finally{confirm.disabled=false;}};
window.addEventListener('pageshow',()=>{document.querySelectorAll('.bulk-item,#bulk-all').forEach(x=>x.checked=false);reset();});
})();