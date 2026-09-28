"""Move o card da issue no GitHub Project conforme o trabalho anda.

  branch criada com o nº da issue no nome   -> Em andamento
  PR aberto/reaberto/pronto pra revisão     -> Em revisão   (issues que o PR fecha)
  review pedindo mudanças                   -> Em andamento
  PR mergeado ou issue fechada              -> Feito
  PR fechado sem merge ou issue reaberta    -> A fazer
  issue nova                                -> entra no Project em A fazer

Roda nas Actions (env GITHUB_EVENT_NAME, GITHUB_EVENT_PATH, GH_TOKEN com escopo
`project`). Também serve à mão: python3 status_project.py <nº issue> "<status>".
"""

import json
import os
import re
import subprocess
import sys

DONO, NUMERO_PROJECT, REPO = "andreojr", 1, "andreojr/sensor-ppg"
A_FAZER, ANDAMENTO, REVISAO, FEITO = "A fazer", "Em andamento", "Em revisão", "Feito"


def graphql(query: str, **vars) -> dict:
    args = ["gh", "api", "graphql", "-f", f"query={query}"]
    for k, v in vars.items():
        args += ["-F" if isinstance(v, int) else "-f", f"{k}={v}"]
    return json.loads(subprocess.run(args, check=True, capture_output=True, text=True).stdout)["data"]


def projeto() -> tuple[str, str, dict[str, str]]:
    d = graphql(
        """query($u:String!,$n:Int!){ user(login:$u){ projectV2(number:$n){ id
             field(name:"Status"){ ... on ProjectV2SingleSelectField{ id options{ id name } } } } } }""",
        u=DONO, n=NUMERO_PROJECT,
    )["user"]["projectV2"]
    return d["id"], d["field"]["id"], {o["name"]: o["id"] for o in d["field"]["options"]}


def item_da_issue(pid: str, numero: int) -> str:
    dono, nome = REPO.split("/")
    d = graphql(
        """query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){ issue(number:$n){ id
             projectItems(first:20){ nodes{ id project{ id } } } } } }""",
        o=dono, r=nome, n=numero,
    )["repository"]["issue"]
    if d is None:
        raise LookupError(f"#{numero} não é issue")
    for it in d["projectItems"]["nodes"]:
        if it["project"]["id"] == pid:
            return it["id"]
    return graphql(
        "mutation($p:ID!,$c:ID!){ addProjectV2ItemById(input:{projectId:$p,contentId:$c}){ item{ id } } }",
        p=pid, c=d["id"],
    )["addProjectV2ItemById"]["item"]["id"]


def move(numeros: list[int], status: str) -> None:
    pid, fid, opcoes = projeto()
    for n in numeros:
        try:
            item = item_da_issue(pid, n)
        except LookupError as e:
            print(f"ignorado: {e}")
            continue
        graphql(
            """mutation($p:ID!,$i:ID!,$f:ID!,$o:String!){ updateProjectV2ItemFieldValue(input:{
                 projectId:$p,itemId:$i,fieldId:$f,value:{singleSelectOptionId:$o}}){ projectV2Item{ id } } }""",
            p=pid, i=item, f=fid, o=opcoes[status],
        )
        print(f"#{n} -> {status}")


def issues_do_pr(numero_pr: int, branch: str) -> list[int]:
    dono, nome = REPO.split("/")
    d = graphql(
        """query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){ pullRequest(number:$n){
             closingIssuesReferences(first:20){ nodes{ number } } } } }""",
        o=dono, r=nome, n=numero_pr,
    )
    nums = {i["number"] for i in d["repository"]["pullRequest"]["closingIssuesReferences"]["nodes"]}
    nums |= set(issue_da_branch(branch))
    return sorted(nums)


def issue_da_branch(branch: str) -> list[int]:
    """filtro/42-butterworth ou 42-butterworth (padrão do botão "Create a branch")."""
    m = re.search(r"(?:^|/)(\d+)-", branch)
    return [int(m.group(1))] if m else []


def main() -> int:
    if len(sys.argv) == 3:
        move([int(sys.argv[1])], sys.argv[2])
        return 0

    evento = os.environ["GITHUB_EVENT_NAME"]
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as f:
        e = json.load(f)

    if evento == "create" and e.get("ref_type") == "branch":
        move(issue_da_branch(e["ref"]), ANDAMENTO)
    elif evento == "pull_request":
        pr = e["pull_request"]
        nums = issues_do_pr(pr["number"], pr["head"]["ref"])
        acao = e["action"]
        if acao in ("opened", "reopened", "ready_for_review") and not pr["draft"]:
            move(nums, REVISAO)
        elif acao == "converted_to_draft":
            move(nums, ANDAMENTO)
        elif acao == "closed":
            move(nums, FEITO if pr["merged"] else A_FAZER)
    elif evento == "pull_request_review":
        if e["review"]["state"] == "changes_requested":
            pr = e["pull_request"]
            move(issues_do_pr(pr["number"], pr["head"]["ref"]), ANDAMENTO)
    elif evento == "issues":
        n = e["issue"]["number"]
        move([n], {"opened": A_FAZER, "reopened": A_FAZER, "closed": FEITO}[e["action"]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
