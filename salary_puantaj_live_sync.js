/* salary-puantaj-live-sync-v3 */
(function(){
 async function refresh(){
  const urls=["/api/personel/salary","/api/personel/maas","/api/my-salary","/api/salary/me"];
  for(const url of urls){
   try{
    const u=new URL(url,location.origin);u.searchParams.set("_ts",Date.now());
    const r=await fetch(u,{cache:"no-store",credentials:"same-origin",headers:{"Cache-Control":"no-cache","Pragma":"no-cache"}});
    if(!r.ok) continue;
    const d=await r.json();
    window.dispatchEvent(new CustomEvent("salary:updated",{detail:d}));
    return;
   }catch(e){}
  }
 }
 addEventListener("pageshow",refresh);
 addEventListener("focus",refresh);
 document.addEventListener("visibilitychange",()=>{if(!document.hidden)refresh()});
 document.addEventListener("DOMContentLoaded",refresh);
 setInterval(()=>{if(!document.hidden)refresh()},60000);
})();