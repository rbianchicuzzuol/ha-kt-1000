# KT-1000 App 0.12.0

Painel de acessos, pessoas e senhas pela Tuya Cloud, independente do Home Assistant Core. Credenciais gerenciadas dentro de cada pessoa, com adição de disponíveis, desassociação e transferência explícita. Cadastros físicos continuam em Pessoas → Usuários da fechadura.

Lista offline sincronizada periodicamente com a Tuya, histórico persistente, códigos offline criados pelo App salvos criptografados e consultáveis, filtros e paginação de 20 registros. Fundo escuro ocupa a viewport inteira.

Desbloqueio remoto desativado por padrão. Leia DOCS.md para atualizar preservando os dados, instalar, importar a integração antiga e entender os limites de sincronização. Requer Supervisor. Publica 17 entidades nativas pelo MQTT Discovery, sem custom_components. O serviço MQTT do Supervisor é detectado automaticamente. Leia INSTALACAO_ENTIDADES.md na raiz do pacote.
