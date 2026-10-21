// Exact decimal conversion: no binary floating point in submitted quantities.
const MassUnits = {
  decimal(value) {
    const match=/^(-?)(\d+)(?:\.(\d+))?$/.exec(String(value).trim());
    if(!match) throw new Error('수량은 일반 숫자 형식으로 입력하세요.');
    return {negative:match[1],digits:match[2]+(match[3]||''),places:(match[3]||'').length};
  },
  convert(value,from,to,validate=false) {
    if(from!==to && !(['kg','g'].includes(from)&&['kg','g'].includes(to))) throw new Error('환산할 수 없는 단위입니다.');
    const n=this.decimal(value), shift=from===to?0:from==='kg'?3:-3;
    let digits=n.digits.replace(/^0+(?=\d)/,'');
    let places=n.places-shift;
    if(places<0) {digits+='0'.repeat(-places);places=0;}
    digits=digits.padStart(places+1,'0');
    let result=places?digits.slice(0,-places)+'.'+digits.slice(-places):digits;
    if(result.includes('.')) result=result.replace(/0+$/,'').replace(/\.$/,'');
    if(validate && (result.split('.')[1]||'').length>6) throw new Error('기준단위 환산 후 소수점 6자리를 초과합니다.');
    return n.negative && result!=='0'?'-'+result:result;
  },
  unit(base,selected) { return ['kg','g'].includes(base)&&['kg','g'].includes(selected)?selected:base; },
};
