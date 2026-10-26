"""Restricted static control evaluation. Never execute source commands or shaders."""
import re,math
from body_selection import evaluate_condition,evaluate_static_value

VARIABLE=re.compile(r'\$(\w+)')
NUMBER=r'-?\d+(?:\.\d+)?'


class ControlProgram:
    def __init__(self,path):
        from static_plan import command_sections
        self.commands=command_sections(path)
        text=path.read_bytes().decode('utf-8-sig',errors='replace')
        self.constants={k.casefold():float(v) for k,v in re.findall(
            r'(?mi)^\s*global\s+(?:persist\s+)?\$(\w+)\s*=\s*('+NUMBER+r')\s*(?:;.*)?$',text)}
        self.present_sections=set()
        def visit(name,stack=()):
            if name in stack:raise ValueError('Present 存在循环命令引用：'+name)
            if name not in self.commands:
                if '\\' in name or name.startswith('builtin'):return
                raise ValueError('Present 引用不存在的命令：'+name)
            self.present_sections.add(name)
            for k,v,_ in self.commands[name]:
                if k=='run':visit(v.casefold(),stack+(name,))
        if 'present' in self.commands:visit('present')
        self.derived=set();self.present_dependencies=set()
        for name in self.present_sections:
            for k,v,_ in self.commands[name]:
                if k.startswith('$'):self.derived.add(k[1:].casefold())
                self.present_dependencies.update(n.casefold() for n in VARIABLE.findall(v))
        key_targets={k[1:].casefold() for name,nodes in self.commands.items() if name.startswith('key')
            for k,_,_ in nodes if k.startswith('$')}
        persisted={k.casefold() for k in re.findall(r'(?mi)^\s*global\s+persist\s+\$(\w+)\s*=',text)}
        self.domains={k:{v} for k,v in self.constants.items() if k not in self.derived or k in key_targets or k in persisted}
        cycles={}
        for name,nodes in self.commands.items():
            if not name.startswith('key'):continue
            for k,v,_ in nodes:
                if not k.startswith('$') or k[1:] not in self.domains:continue
                values=v.split(',')
                if all(re.fullmatch(NUMBER,x.strip()) for x in values):
                    cycles.setdefault(k[1:],set()).update(float(x) for x in values)
        for variable,value in re.findall(r'\$(\w+)\s*(?:==|!=|<=|>=|<|>)\s*('+NUMBER+r')',text):
            variable=variable.casefold()
            if variable in self.domains and variable in key_targets|persisted:self.domains[variable].add(float(value))
        for k,values in cycles.items():self.domains[k]=values|{self.constants[k]}
        # Writes outside Present/keys cannot be reconstructed from a static pass.
        self.runtime_targets={k[1:].casefold() for name,nodes in self.commands.items()
            if name not in self.present_sections and name!='constants' and not name.startswith('key')
            for k,_,_ in nodes if k.startswith('$')}
        for k in self.runtime_targets:
            if k not in persisted and k not in key_targets:self.domains.pop(k,None)

    def _present_inputs_for(self,target):
        found=set();frames=[];target=target.casefold()
        for k,v,_ in self.commands.get('present',[]):
            if k=='if':
                frames.append(v);continue
            if k=='elif' and frames:
                frames[-1]=v;continue
            if k=='else' and frames:
                frames[-1]='';continue
            if k=='endif':
                if frames:frames.pop()
                continue
            if k.startswith('$') and k[1:].casefold()==target:
                found.update(n.casefold() for n in VARIABLE.findall(v))
                for condition in frames:
                    found.update(n.casefold() for n in VARIABLE.findall(condition))
        found.discard(target)
        return found

    def domains_for(self,variables):
        needed={v.casefold() for v in variables}
        extras=set()
        for var in list(needed):
            if var in self.derived:
                inputs=self._present_inputs_for(var)
                extras|=inputs
                if inputs:needed.discard(var)
        needed|=extras
        return {k:sorted(v) for k,v in sorted(self.domains.items()) if k in needed}

    def resolve(self,overrides):
        for k,v in overrides.items():
            if k not in self.domains or not math.isfinite(v) or v not in self.domains[k]:
                raise ValueError('不是来源声明的静态控制值：'+k)
        values={k:v for k,v in self.constants.items()
            if k not in self.runtime_targets or k in self.domains}
        values.update(overrides)
        def targets(name,seen=None):
            seen=set() if seen is None else seen
            if name in seen:return set()
            seen.add(name);result=set()
            for k,v,_ in self.commands.get(name,[]):
                if k.startswith('$'):result.add(k[1:].casefold())
                elif k=='run':result|=targets(v.casefold(),seen)
            return result
        def execute(name):
            frames=[]
            for k,v,_ in self.commands.get(name,[]):
                if k=='if':
                    selected=evaluate_condition(v,values)
                    frames.append({'previous':[selected],'active':selected});continue
                if k in ('elif','else') and frames:
                    frame=frames[-1];prior=True if True in frame['previous'] else None if None in frame['previous'] else False
                    candidate=evaluate_condition(v,values) if k=='elif' else True
                    frame['active']=False if prior is True or candidate is False else None if prior is None or candidate is None else True
                    if k=='elif':frame['previous'].append(candidate)
                    continue
                if k=='endif':
                    if not frames:raise ValueError('Present 条件结构不完整')
                    frames.pop();continue
                active=[f['active'] for f in frames]
                if False in active:continue
                if k.startswith('$'):
                    target=k[1:].casefold();result=evaluate_static_value(v,values)
                    if None in active or result is None:values.pop(target,None)
                    else:values[target]=result
                elif k=='run':
                    if None in active:
                        for target in targets(v.casefold()):values.pop(target,None)
                    else:execute(v.casefold())
            if frames:raise ValueError('Present 条件结构不完整')
        execute('present')
        return values


def load_control_program(path):
    from pathlib import Path
    return ControlProgram(Path(path))
