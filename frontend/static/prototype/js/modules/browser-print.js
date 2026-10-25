// Use the browser's print preview directly; keep the application page in place.
const BrowserPrint = {
  frame: null,
  print(html,onClose) {
    if(this.frame) return false;
    const frame=document.createElement('iframe');
    frame.title='인쇄 문서';
    frame.style.cssText='position:fixed;left:-10000px;top:0;width:1200px;height:900px;border:0;';
    frame.setAttribute('aria-hidden','true');
    this.frame=frame;
    let cleaned=false;
    const cleanup=(completed=false)=>{if(cleaned)return;cleaned=true;frame.remove();if(this.frame===frame)this.frame=null;if(completed)onClose?.();};
    let started=false;
    frame.onload=async()=>{
      if(started) return;
      started=true;
      try {
        await frame.contentDocument.fonts?.ready;
        await new Promise(resolve=>frame.contentWindow.requestAnimationFrame(()=>frame.contentWindow.requestAnimationFrame(resolve)));
        frame.contentWindow.addEventListener('afterprint',()=>cleanup(true),{once:true});
        frame.contentWindow.focus();
        frame.contentWindow.print();
      } catch(error) {
        cleanup();
        App.showToast('error','인쇄',error.message||'인쇄 창을 열 수 없습니다.');
      }
    };
    try {
      document.body.appendChild(frame);
      frame.contentDocument.open();
      frame.contentDocument.write(html);
      frame.contentDocument.close();
    } catch(error) {cleanup();throw error;}
    return true;
  },
};
