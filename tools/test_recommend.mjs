// Validate web/recommend.js headlessly: eval bundle + recommend.js, build a
// synthetic vm (hand pool + opponent board), run recommendBoard, sanity-check.
import { readFileSync } from 'node:fs';
(0,eval)(readFileSync('web/yisim.bundle.js','utf8'));
(0,eval)(readFileSync('web/recommend.js','utf8'));
await globalThis.yisim.ready();

const card=(name,level=1)=>({name,level});
// pool of cards the player "holds" (board + hand), varied power so order matters
const pool=[
  card('三峰剑'),card('云剑•探云'),card('锻体'),card('炼体'),
  card('三峰剑'),card('云剑•探云',2),card('护身灵气'),card('剑挡'),
  card('聚气'),card('回春'),
];
const vm={
  round:6, phase:'prep',
  me:{
    hp:80, tipo:10, max_tipo:10, xiuwei:120, realm_tier:3, unlocked:6,
    board:[card('锻体'),null,null,null,null,null],     // currently placed
    hand: pool.slice(1),                                 // rest in hand
    fates:[], seasonal:[],
  },
  opponent:{
    hp:70, tipo:8, xiuwei:115, realm_tier:3, unlocked:6, boardFromRound:5,
    board:[card('三峰剑'),card('云剑•探云'),card('锻体'),null,null,null],
    fates:[],
  },
};

const t0=performance.now();
const rec=await globalThis.recommendBoard(vm,{settings:{damageMode:'matchup'},budget:600,finalists:6});
const ms=performance.now()-t0;

function showSlots(slots){return slots.map(s=>s?`${s.name}${s.level>1?'·lv'+s.level:''}`:'·').join(' | ');}
console.log(`\n=== recommendBoard done in ${ms.toFixed(0)}ms, meta=`,JSON.stringify(rec.meta));

console.log(`\n[伤害最大化] (solo)`);
console.log('  摆法:',showSlots(rec.damageMax.slots));
console.log(`  前8伤害=${rec.damageMax.damage}`);

console.log(`\n[打赢对方·上一轮R${rec.oppRound}牌面] (matchup)`);
if(rec.beatOpponent){
  console.log('  摆法:',showSlots(rec.beatOpponent.slots));
  console.log(`  胜率=${(rec.beatOpponent.winRate*100).toFixed(0)}%  结果=${rec.beatOpponent.outcome} @T${rec.beatOpponent.endTurn}  我方HP残=${rec.beatOpponent.myHp} 对方HP残=${rec.beatOpponent.oppHp}`);
}else console.log('  (无对手牌面)');

// sanity: compare damageMax vs a naive "pool order" arrangement
const naive=pool.slice(0,6).map(c=>({name:c.name,level:c.level,isDream:false}));
const nr=await globalThis.yisim.simulate(naive,{deckSlots:6,maxTurns:32,mode:'solo',rollMode:'average',playerState:{hp:80,maxHp:80,physique:10,cultivation:120}});
console.log(`\n[对照] 朴素按池顺序摆: 前8伤害=${nr.first8Turns}`);
console.log(`推荐伤害 ${rec.damageMax.damage} ${rec.damageMax.damage>=nr.first8Turns?'>= 对照 ✓':'< 对照 ✗(异常)'}`);
