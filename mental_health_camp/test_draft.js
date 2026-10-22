const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');

test('drafts contain only answers, isolate course keys and survive failed submissions',()=>{
    const stored=new Map();
    const fields=[{name:'csrf_token',type:'hidden',value:'secret'},{name:'version_id',type:'hidden',value:'1'},
        {name:'q_text',type:'textarea',value:'draft'}, {name:'q_scale',type:'radio',value:'0',checked:true},
        {name:'q_multi',type:'checkbox',value:'A',checked:true},{name:'q_multi',type:'checkbox',value:'B',checked:false}];
    const form={dataset:{draftKey:'answers:1:1:1:1'},querySelectorAll:()=>fields.filter(x=>x.name.startsWith('q_'))};
    const context=vm.createContext({document:{getElementById:()=>form},localStorage:{getItem:k=>stored.get(k)??null,setItem:(k,v)=>stored.set(k,v)}});
    vm.runInContext(fs.readFileSync(path.join(__dirname,'static/js/draft.js'),'utf8'),context);
    context.saveDraft(1);
    assert.deepEqual(JSON.parse(stored.get(form.dataset.draftKey)),{text:'draft',scale:'0',multi:['A']});
    assert.ok(!stored.get(form.dataset.draftKey).includes('secret'));
    fields[2].value='';fields[3].checked=false;context.initFormDraft(1);
    assert.equal(fields[2].value,'draft');assert.equal(fields[3].checked,true);
    form.dataset.draftKey='answers:2:1:1:1';fields[2].value='another user';context.initFormDraft(1);
    assert.equal(fields[2].value,'another user');
    form.dataset.draftKey='answers:1:1:2:1';context.saveDraft(1);
    assert.equal(JSON.parse(stored.get('answers:1:1:1:1')).text,'draft');
    assert.equal(stored.size,2);
});

test('course hidden answer values escape attribute delimiters and zero is selectable',()=>{
    const container={innerHTML:''};
    const context=vm.createContext({document:{getElementById:()=>container}});
    vm.runInContext(fs.readFileSync(path.join(__dirname,'static/js/camp_content.js'),'utf8')+'\nthis.Manager=CampStepManager;',context);
    context.Manager.prototype._render=function(){};
    const manager=new context.Manager({questions:[{id:'zero',type:'likert',min:0,max:2}],enrollmentId:1,dayNumber:1,versionId:9,
        initialAnswers:{zero:0,text:'" onfocus="alert(1)'},csrfToken:'token',formAction:'/user/form/1/1'});
    assert.match(manager._renderLikert(manager.questions[0],false),/likert_camp_zero_0/);
    manager._renderComplete();
    assert.match(container.innerHTML,/name="version_id" value="9"/);
    assert.match(container.innerHTML,/value="&quot; onfocus=&quot;alert\(1\)"/);
    assert.ok(!container.innerHTML.includes('value="" onfocus="'));
});

test('trend charts preserve version series and retain zero-valued points',()=>{
    let chart;
    const context=vm.createContext({document:{getElementById:()=>({getContext:()=>({})})},
        Chart:class {constructor(ctx,options){chart=options;}}});
    vm.runInContext(fs.readFileSync(path.join(__dirname,'static/js/dashboard.js'),'utf8'),context);
    context.initLikertChart('trend',{
        '1:scale':{label:'旧定义',min:0,labels:['零分','一分'],data:[{day:1,value:0}]},
        '2:scale':{label:'新定义',data:[{day:2,value:8}]}
    });
    assert.equal(chart.data.datasets.length,2);
    assert.deepEqual(Array.from(chart.data.datasets[0].data),[0,null]);
    assert.deepEqual(Array.from(chart.data.datasets[1].data),[null,8]);
    assert.equal(chart.options.scales.y.max,8);
});
