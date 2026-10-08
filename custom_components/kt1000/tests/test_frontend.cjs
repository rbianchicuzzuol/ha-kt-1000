const fs=require('fs'),vm=require('vm'),assert=require('assert');
let Panel;const ctx={HTMLElement:class{attachShadow(){return {}}},customElements:{define:(name,cls)=>{assert.equal(name,"kt1000-panel");Panel=cls}},console,Intl,Date,setTimeout};
vm.runInNewContext(fs.readFileSync(__dirname+'/../app/frontend/kt1000-panel.js','utf8'),ctx);
const p=new Panel();p.data={history:Array.from({length:45},(_,i)=>({event_time:1000+i,person:'Ana',credential_id:String(i),code:'unlock_card'}))};
let html=p.accessTable();assert.equal((html.match(/<tr><td>/g)||[]).length,20);assert(html.includes('Página 1 de 3'));
p.accessPage=3;html=p.accessTable();assert.equal((html.match(/<tr><td>/g)||[]).length,5);assert(html.includes('Página 3 de 3'));
p.search='missing';html=p.accessTable();assert(html.includes('0 registros'));assert.equal(p.accessPage,1);
p.search='<img>';html=p.accessTable();assert(html.includes('&lt;img&gt;'));assert(!html.includes('value="<img>"'));
console.log('Frontend: pagination, last page, empty filter and escaping passed.');

assert(fs.readFileSync(__dirname+"/../app/frontend/index.html","utf8").includes("<kt1000-panel>"));

p.shadowRoot={querySelector:()=>null,querySelectorAll:()=>[]};
p.data={history:[],credentials:[],people:[],online:false,communication_pending:false,communication_error:'Tuya token error 1004: sign invalid <test>',title:'KT-1000',remote_unlock_enabled:false};p.tab='overview';p.render();assert(p.shadowRoot.innerHTML.includes('1004'));assert(p.shadowRoot.innerHTML.includes('&lt;test&gt;'));assert(p.shadowRoot.innerHTML.includes('id="refreshConnection"'));assert(p.shadowRoot.innerHTML.includes('min-height:100vh'));assert(fs.readFileSync(__dirname+'/../app/frontend/index.html','utf8').includes('html{height:100%;background:#111'));
console.log('Frontend: communication error and full viewport background passed.');

p.passwordMode='offline';p.offlinePasswords=[{id:'123',name:'Teste <x>',type:'once',invalid_time:Math.floor(Date.now()/1000)+3600,status:1,has_code:true},{id:'456',name:'Old',type:'multiple',invalid_time:1,status:3,has_code:false}];
let off=p.passwordsView();assert(off.includes('Teste &lt;x&gt;'));assert(off.includes('Ver código'));assert(!off.includes('Old'));
p.showInvalidOffline=true;off=p.passwordsView();assert(off.includes('Old'));assert(off.includes('Código não disponível'));
p.offlineFilter='multiple';off=p.passwordsView();assert(!off.includes('Teste &lt;x&gt;'));assert(off.includes('Old'));
console.log('Frontend: offline list, invalid filter, types and reveal button passed.');

p.passwordMode='online';p.showDeleted=false;p.tempPasswords=[{id:1,name:'Vencida',phase:2,invalid_time:1},{id:2,name:'Ativa',phase:2,invalid_time:4102444800}];p.tempPasswordError=null;
const online=p.passwordsView();assert(online.includes('pwdDeleteRecord" data-id="1"'));assert(online.includes('pwdDelete" data-id="2"'));assert(online.includes('Excluir registro'));
console.log('Frontend: expired record deletion separated from active credential deletion passed.');

p.data.people=[{name:'Ana',credentials:['unlock_card:1']},{name:'Bia',credentials:['unlock_password:2']}];p.data.credentials=[{key:'unlock_card:1',last_used:1},{key:'unlock_password:2',last_used:1},{key:'unlock_fingerprint:3',last_used:1}];
assert.equal(p.availableCredentials().map(c=>c.key).join(','),'unlock_fingerprint:3');
p.tab='people';p.peopleMode='local';p.selectedPerson='Ana';let peopleHtml=p.peopleHub();assert(peopleHtml.includes('Transferir'));assert(peopleHtml.includes('Desassociar'));assert(peopleHtml.includes('Adicionar credencial (1)'));assert(peopleHtml.includes('unlock_card:1'));assert(!peopleHtml.includes('unlock_password:2'));
p.peopleMode='lock';p.selectedLockUser='tuya-1';p.lockUsers=[{user_id:'tuya-1',nick_name:'Ana',unlock_detail:[{dp_code:'unlock_password',unlock_list:[{unlock_sn:'1',unlock_name:'Senha'}]}]}];peopleHtml=p.peopleHub();assert(peopleHtml.includes('Cadastrar senha'));assert(peopleHtml.includes('Cadastrar digital'));assert(peopleHtml.includes('Cadastrar tag/cartão'));assert(peopleHtml.includes('Trocar senha'));assert(peopleHtml.includes('Excluir da fechadura'));
p.render();assert(!p.shadowRoot.innerHTML.includes('data-tab="credentials"'));assert(p.shadowRoot.innerHTML.includes('data-tab="people"'));
console.log('Frontend: person ownership, detail actions, unified navigation and physical enrollment options passed.');
