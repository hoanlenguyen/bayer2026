import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createServer } from 'vite';
const server = await createServer({server:{middlewareMode:true},appType:'custom'});
try {
  const { ENTITIES, EDGES } = await server.ssrLoadModule('/src/data/estate.ts');
  const { setEstate, neighborhood } = await server.ssrLoadModule('/src/lib/estate.ts');
  const add = (s,t,basis='lineage') => EDGES.push({s,t,basis,rel:'feeds'});
  const reset = () => { ENTITIES.length=0; EDGES.length=0; ['A','B','C','owner','candidate'].forEach(id=>ENTITIES.push({id,type:'model'})); };
  await test('directed impact handles cycles without treating ownership or candidates as dependencies', () => {
    reset(); add('A','B'); add('B','C'); add('C','B'); add('owner','B','join'); add('B','candidate','candidate'); setEstate([...ENTITIES], [...EDGES]);
    assert.deepEqual([...neighborhood('B',3,new Set(),'upstream').keys()].sort(), ['A','B','C']);
    assert.deepEqual([...neighborhood('B',3,new Set(),'downstream').keys()].sort(), ['B','C']);
    assert(!neighborhood('B',1,new Set()).has('candidate'));
    assert(neighborhood('B',1,new Set(),'all',true).has('candidate'));
  });
  await test('broad neighborhoods cap rendering while retaining accurate reachable counts', () => {
    reset(); for(let i=0;i<120;i++){ ENTITIES.push({id:`x${i}`,type:'model'}); add('A',`x${i}`); } setEstate([...ENTITIES], [...EDGES]);
    assert.equal(neighborhood('A',1,new Set()).size,90);
    assert.equal(neighborhood('A',1,new Set(),'all',false,Infinity).size,121);
    assert.equal(neighborhood('A',1,new Set(['model'])).size,1);
  });
} finally { await server.close(); }
