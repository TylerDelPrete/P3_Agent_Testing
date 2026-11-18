import fs from 'node:fs';
import path from 'node:path';
import {executeMock, schemaFor} from './mocks.js';

export default {
  id:'ps3-mock-tools', name:'InjecAgent bounded mock tools',
  register(api) {
    const dir=path.resolve(api.pluginConfig.runDir);
    const read=name=>JSON.parse(fs.readFileSync(path.join(dir,name),'utf8'));
    const fixture=read('input.json'), definitions=read('tool_definitions.json');
    const state=read('initial_state.json');
    let count=0;
    const record=event=>fs.appendFileSync(path.join(dir,'events.jsonl'),JSON.stringify({time:new Date().toISOString(),...event})+'\n');
    if(api.pluginConfig.systemPrompt)api.on('before_prompt_build',()=>{
      record({type:'experiment_prompt_applied',system_prompt:api.pluginConfig.systemPrompt});
      return {systemPrompt:api.pluginConfig.systemPrompt};
    });
    for(const [name,definition] of Object.entries(definitions))api.registerTool({
      name,label:name,description:definition.summary,parameters:schemaFor(definition),
      async execute(callId,args) {
        count++;
        const limited=count>10;
        // Limit checked BEFORE dispatch, so even private reads cannot occur past it.
        const result=limited?{output:{error:'Test tool-call limit reached'},executed:false,fixtureDelivered:false,
          effect:null,unsupported:false,authorization:'not_evaluated'}:executeMock(name,args,state,fixture,definitions);
        const text=typeof result.output==='string'?result.output:JSON.stringify(result.output);
        record({type:'tool_result',name,call_id:callId,arguments:args,authorization:result.authorization,
          executed:result.executed,fixture_delivered:result.fixtureDelivered,effect:result.effect,
          unsupported:result.unsupported,tool_limit:limited,retrieval_mismatch:result.retrievalMismatch||false,
          argument_normalization:result.argumentNormalization||false,output:text});
        fs.writeFileSync(path.join(dir,'final_state.json'),JSON.stringify(state,null,2));
        return {content:[{type:'text',text}]};
      }
    });
  }
};
