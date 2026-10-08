# KT-1000 App 0.11.0

## Pessoas: novo fluxo de credenciais

A aba principal Credenciais foi incorporada a **Pessoas**. Nenhuma associação existente foi apagada e não é necessário importar os dados novamente.

### Pessoas e acessos

1. Abra Pessoas, escolha a pessoa e clique em **Gerenciar credenciais**.
2. **Adicionar credencial** mostra apenas credenciais conhecidas sem associação a outra pessoa no App.
3. **Desassociar** libera a credencial para adicionar a outra pessoa; não exclui a credencial na fechadura nem revoga seu acesso físico.
4. **Transferir** permite corrigir uma atribuição errada diretamente, escolhendo outra pessoa. Não é preciso desassociar primeiro. O backend verifica quem é o dono atual para evitar transferências silenciosas por uma tela desatualizada.
5. **Editar nome** preserva as credenciais e rejeita nomes duplicados.
6. **Excluir pessoa do App** remove somente esse perfil local. As credenciais continuam disponíveis para associação; nenhum usuário/credencial Tuya é excluído.

As associações são usadas para identificar registros de acesso, inclusive acessos passados. Uma credencial importada sem histórico permanece no catálogo mesmo depois de desassociar ou excluir a pessoa. Credenciais de outras pessoas nunca são oferecidas no seletor Adicionar; só podem mudar de dono pela ação Transferir da pessoa atual.

### Usuários da fechadura

Dentro da mesma área Pessoas, abra **Usuários da fechadura**, selecione um usuário e clique em **Gerenciar credenciais**. As operações físicas continuam disponíveis:

- Cadastrar senha, digital e tag/cartão: solicita o modo de cadastramento na Tuya; conclua a captura no local.
- Trocar senha: preserva o fluxo de cadastro de uma nova senha para o mesmo usuário.
- Renomear credencial e **Excluir da fechadura**.
- Editar/excluir usuário e alterar perfil administrativo, conforme suporte do produto.

Esta área representa os usuários reais retornados pela Tuya. Não associamos automaticamente um cadastro local a um usuário físico só porque têm nomes ou números parecidos. **Desassociar** no App muda identificação; **Excluir da fechadura** solicita revogação física. Essas operações têm consequências diferentes e por isso aparecem em contextos separados dentro de Pessoas.

As opções de cadastramento foram mantidas, mas não foram acionadas durante o desenvolvimento. Enquanto estiver longe do apartamento, não inicie captura que precise ser concluída na fechadura.

## Senhas online vencidas: erro 2304

A Tuya retorna `2304: password has expired!` ao tentar excluir uma senha já vencida pelo endpoint de exclusão da credencial. Para essas senhas, o botão agora é **Excluir registro**: usa o endpoint documentado `DELETE /v1.0/devices/{device_id}/door-lock/temp-passwords/{password_id}/record`, que remove o registro histórico na cloud. Senhas ativas continuam com Excluir, usando o endpoint da credencial.

Antes de excluir um registro, o backend consulta metadados atuais na Tuya e permite a operação somente se a senha estiver vencida ou já excluída. Não altera a validade, não reativa senhas e não solicita abertura. A remoção só é apresentada como sucesso se a Tuya retornar `result: true`. Se o produto/projeto não permitir esse endpoint, o erro continua visível; não escondemos o registro localmente simulando sincronização com o celular.

A documentação desse endpoint é arquivada; seu suporte real ainda precisa ser verificado nesta fechadura. Nenhum registro foi excluído durante o desenvolvimento. A captura confirma o erro no endpoint antigo, mas os testes do novo são simulados.

Referência: https://developer.tuya.com/en/docs/archived-documents/8b39523df2?id=Kats0cdhnl0cj

## Atualizar sem perder dados

Substitua os arquivos de código na pasta do App/repositório usado na instalação e recarregue a loja. Use **Atualizar** ou **Reconstruir** e reinicie apenas o App. Não desinstale, não altere o slug `kt1000` e não apague `/data`. As configurações, pessoas e histórico da instalação existente são preservados; as novas estruturas de senhas são acrescentadas ao mesmo arquivo.

Este ZIP não publica alterações no GitHub nem atualiza automaticamente seu servidor. Instalações locais usam `/addons/kt1000`; instalações via repositório precisam receber esses arquivos no mesmo repositório/pasta que o Supervisor utiliza.

## Senhas offline e sincronização com o celular

A aba Offline agora mostra nome, ID, tipo, início, fim e status. Há filtros para uso único/por período/códigos de limpeza e uma opção para mostrar utilizadas e inválidas. A listagem é paginada em 20 registros.

- O App consulta a Tuya periodicamente, usando `scan_interval` (padrão 30 segundos). Consultas demoradas podem aumentar o intervalo real.
- A listagem offline busca todas as páginas da API com os tipos `multiple,once,clear_one,clear_all`; corrige os antigos parâmetros `0,1`.
- Senhas criadas no celular e mudanças de nome/status são refletidas quando a API Tuya as retornar para o mesmo dispositivo/projeto. Nenhum endpoint privado do aplicativo móvel é usado.
- Criar uma senha neste App chama a Tuya. O registro local é salvo após essa chamada. A visualização no celular depende de a Tuya disponibilizar o registro para a mesma conta/fechadura; não foi validada no dispositivo real.
- O botão Atualizar consulta a lista sem enviar comandos de abertura. A atualização periódica também é somente leitura.
- Se a sincronização falhar, a lista local continua disponível e mostra um aviso. Um registro que deixou de ser retornado aparece como histórico local/não confirmado; não fingimos que ele foi excluído ou continua disponível na fechadura.
- “Gerada” significa criação registrada, mas não confirma uso. “Disponível”, “Utilizada” e “Inválida” vêm do status retornado pela Tuya; validade vencida/agendamento também são calculados pelas datas.

## Guardar e consultar o código

Novas senhas offline geradas neste App têm o código salvo criptografado em `/data/access.json`. A chave está em `/data/passwords.key`, com permissão de arquivo 0600. O botão **Ver código** revela o valor apenas quando solicitado, sem executar operações na fechadura. O código não é incluído na resposta de listagem.

Preserve os DOIS arquivos em backups/restaurações; perder a chave impede decifrar os códigos. O backup do App contém seu diretório de dados. A criptografia evita PINs em texto puro no arquivo de histórico; quem tiver acesso aos dois arquivos poderá decifrá-los.

Senhas geradas antes desta atualização ou pelo celular podem ser listadas, mas seus códigos não são recuperados por este endpoint Tuya. Nesses casos aparece **Código não disponível**. Não é preciso recriar uma senha antiga para que sua validade continue funcionando.

Se a Tuya gerar a senha mas o disco não permitir salvar, a interface ainda mostra o código e avisa para anotá-lo. Não repita a criação para tentar salvar: isso poderia gerar outra senha.

Senhas online continuam sendo consultadas na Tuya e são atualizadas quando a aba está aberta. O App não armazena o PIN digitado de senhas online. Esta versão adiciona o cofre de códigos OFFLINE.

Códigos de limpeza só produzem efeito quando digitados fisicamente na fechadura. Gerar um código não confirma a remoção de senhas.

## Fundo da interface

O fundo escuro é aplicado ao HTML, ao corpo e ao componente com altura mínima de viewport (`100vh`/`100dvh`), para eliminar a faixa branca abaixo do conteúdo no Ingress. Depois de atualizar/reconstruir o App, feche e reabra a página. Se aparecer a versão antiga, recarregue sem cache (Cmd+Shift+R no Chrome do Mac).

## Instalação inicial

Requer Home Assistant OS ou instalação com Supervisor e loja de Apps. Home Assistant Container/Core puro não possui essa loja.

1. Faça backup do HA.
2. Extraia a pasta `kt1000` para `/addons/kt1000`, com `config.yaml` diretamente nessa pasta. Não copie para `custom_components`.
3. Recarregue a loja de Apps e instale o App local KT-1000. A construção baixa Python e dependências da internet.
4. Configure `client_id`, `client_secret`, `device_id` e região. A integração 0.8 fornecida usava `us`.
5. Salve, inicie e habilite Mostrar na barra lateral.

Os valores da antiga integração estão na entrada `domain: kt1000`, seção `data`, do arquivo `/config/.storage/core.config_entries`. Abra somente para copiar; não altere esse arquivo nem compartilhe seus segredos.

## Importação antiga de pessoas e acessos

Copie `/config/.storage/kt1000.access` para seu computador. No App clique em Importar dados, selecione o arquivo e informe a chave `entry_id` encontrada em `data.history`/`data.people`. A importação mescla pessoas por nome e acessos por horário/método/ID, sem operações na fechadura. Quem já importou não precisa repetir a importação ao atualizar.

A versão 0.11.0 inclui a ponte custom_components/kt1000_app para recriar sensores/eventos nativos sem MQTT. Instale conforme INSTALACAO_ENTIDADES.md. Os novos IDs pertencem à ponte; revise dashboards/automações antes de desativar a integração antiga. A ponte usa as associações atuais do App.

## Desbloqueio e comunicação

Mantenha `remote_unlock_enabled: false` enquanto estiver longe do apartamento. A consulta, sincronização e revelação de códigos não desbloqueiam a porta. O App só envia abertura quando essa opção está habilitada e o usuário confirma explicitamente. `open_door` é o modo padrão; `door_operate` depende de suporte específico do produto. Não há tentativa automática em outro endpoint de abertura.

O erro 1004 (`sign invalid`) é de autenticação. Recoloque as credenciais REAIS do mesmo projeto Tuya, salve e reinicie somente o App. Não use senha Smart Life, local_key ou asteriscos de campos mascarados. O App remove espaços externos e informa credenciais vazias/mascaradas. O algoritmo de assinatura continua igual ao da integração antiga.

A interface e as operações de gerenciamento são exclusivas pelo Ingress. A ponte usa uma API separada de leitura em 8100, autenticada por bridge_token; por padrão essa porta não é publicada no host. Usuários autorizados a entrar neste App são tratados como operadores de gerenciamento e podem consultar códigos salvos. Restrinja o acesso à interface a quem administra a fechadura.

## Validação

48 testes Python com mocks e substitutos das interfaces HA, incluindo páginas Tuya, nomes/campos offline, persistência após reinício, código criptografado, perda de chave, mescla com cadastro antigo, alterações do celular simuladas, falha cloud, falha de disco, autenticação, exclusão e bloqueio remoto. Testes Node de paginação, filtros offline, botão de código, escape HTML e fundo de viewport. Verificações de sintaxe e integridade do ZIP.

Não houve acesso ao seu HA/Tuya nem comandos reais à fechadura. A imagem Docker/Supervisor não foi construída neste ambiente. O layout ainda precisa de conferência no navegador do seu HA; os testes de frontend verificam HTML/CSS gerados, sem um navegador real disponível aqui.

```bash
cd kt1000
python -m unittest discover -s tests -v
node tests/test_frontend.cjs
```

## Referências

- https://developers.home-assistant.io/docs/apps/configuration/
- https://developers.home-assistant.io/docs/apps/tutorial/
- https://developer.tuya.com/en/docs/archived-documents/b681b8fa14?id=Kdt9r271ozo06
- https://developer.tuya.com/en/docs/legacy-reference-of-cloud-service-apis/doorlock-api-password?id=Kcojq8ddyq7vm
