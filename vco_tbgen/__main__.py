import argparse
import json
from pathlib import Path
import sys
import vco_tbgen

def main():
    parser=argparse.ArgumentParser(prog='vco-tbgen');sub=parser.add_subparsers(dest='action',required=True)
    for name in ['browse','describe','classify','plan','materialize','run','results','dut-only','from-design-lab']:
        cmd=sub.add_parser(name);cmd.add_argument('--json',action='store_true');cmd.add_argument('--output')
        if name in ['browse','describe']:cmd.add_argument('--cds-lib',required=True)
        if name=='describe':cmd.add_argument('--lib',required=True);cmd.add_argument('--cell',required=True);cmd.add_argument('--view',default='symbol')
        if name not in ['browse','describe']:cmd.add_argument('input');
        if name=='materialize':cmd.add_argument('--plan')
        if name=='from-design-lab':
            cmd.add_argument('--level', choices=['L-b', 'L-c'], required=True)
        if name in ('plan', 'materialize'):
            cmd.add_argument('--level', choices=['L-b', 'L-c', 'L-d'])

    args=parser.parse_args()
    try:
        if args.action=='browse':value=vco_tbgen.browse_libraries(args.cds_lib)
        elif args.action=='describe':value=vco_tbgen.describe_cell({k:getattr(args,k) for k in ['lib','cell','view']},args.cds_lib)
        else:
            data=json.loads(Path(args.input).read_text())
            if args.action == 'dut-only':
                value = vco_tbgen.dut_only(**data)
            elif args.action == 'from-design-lab':
                value = vco_tbgen.from_design_lab(**data, completeness=args.level)
            else:
                if getattr(args, 'level', None):
                    if data.get('completeness', args.level) != args.level:
                        raise ValueError('Requested level differs from the prepared spec')
                    data['completeness'] = args.level
                if args.action == 'materialize':
                    value = vco_tbgen.materialize(data, json.loads(Path(args.plan).read_text()) if args.plan else None)
                else:
                    value = getattr(vco_tbgen, 'classify_ports' if args.action == 'classify' else args.action)(data)
        code=1 if value.get('status') in ['failed','needs_input'] else 0
    except Exception as e:value={'status':'failed','error':str(e)};code=1
    text=json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)
    if args.output:Path(args.output).write_text(text+'\n')
    print(text);return code
if __name__=='__main__':sys.exit(main())
