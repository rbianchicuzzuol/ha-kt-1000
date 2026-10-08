# 0.11.0

- Ponte local autenticada sem MQTT; 17 entidades nativas com dispositivo e unique_id.
- API independente somente GET; não disponibiliza serviços ou comandos de abertura.
- Bateria, tranca interna, último acesso/usuário/método/credencial, histórico, credenciais não associadas, alarmes, campainha e diagnósticos.
- Eventos nativos e eventos de automação compatíveis com os nomes antigos; sem reproduzir eventos históricos ao iniciar.
- Associações de pessoas obtidas do App em cada atualização, sem cópia desatualizada no HA.
- Contadores usam todo o histórico local; atributos do histórico limitados aos últimos 25 registros.
- Últimos valores reportados persistidos para não desaparecerem em consultas sem novos relatórios.
- Falha na nuvem torna os sensores de dados indisponíveis; diagnóstico continua mostrando a falha. App parado torna a ponte indisponível.

# 0.10.0

- Gestão centralizada em Pessoas com cartões e detalhe individual das credenciais.
- Adicionar mostra somente credenciais sem associação local.
- Desassociar e transferir pela pessoa, com confirmação de dono atual no backend.
- Editar nome preservando vínculos; nomes duplicados são rejeitados.
- Catálogo conserva credenciais sem histórico após desassociar/excluir pessoa.
- Usuários Tuya agrupados por pessoa na mesma área; cadastro físico, troca de senha, renomeação e exclusão preservados.
- Rótulos distinguem identificação local de exclusão física na fechadura.
- Correção de transferência inválida que podia remover o vínculo anterior.

# 0.9.3

- Botão Excluir registro para senhas online vencidas/excluídas, usando o endpoint de histórico Tuya.
- Verificação do estado atual no backend antes de excluir histórico; bloqueia senhas ativas.
- Erro 2304 explicado sem reativar a senha nem ocultar registros localmente.
- Testes de recusa para senha ativa, ID inválido, falso sucesso e erro de permissão.

# 0.9.2

- Consulta offline com nomes de tipos corretos, campos Tuya normalizados e todas as páginas.
- Sincronização periódica de metadados do celular/cloud e histórico local conservado nas falhas.
- Persistência de novas senhas offline com código criptografado e botão Ver código.
- Filtros por tipo, utilizadas/inválidas e paginação de 20 registros.
- Atualização sem perder dados já importados.
- Fundo HTML/body/componente com altura de viewport, incluindo viewport dinâmica.
- Testes de reinício, criptografia, sincronização, falha de disco/cloud e migração.

# 0.9.1

- Fundo escuro com altura mínima de viewport; remove a área branca no Ingress.
- Mensagem de autenticação 1004 e falhas de comunicação visíveis na visão geral.
- Normalização de espaços externos em credenciais; diagnóstico de valores vazios, mascarados ou espaços internos, sem expor segredos.
- Atualização automática do status a cada 30 segundos e botão de consulta somente leitura.
- Preservação dos dados já importados. O algoritmo de assinatura continua igual ao da integração 0.8; credenciais reais inválidas exigem correção nas opções.

# 0.9.0

- Conversão em App standalone com Ingress e dados persistentes.
- Tipos string e janelas horárias corretas para senhas offline v1.1.
- Preservação de password_id para exclusão e detalhes de senhas online.
- Exclusão com confirmação positiva da Tuya; erros continuam visíveis.
- Paginação de 20 acessos, busca e filtro.
- Seleção de endpoint remoto, bloqueio padrão e confirmação obrigatória.
- Importação de pessoas e histórico de kt1000.access.
- Testes isolados sem comandos reais à fechadura.
