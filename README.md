# Sales Pitch AI V2.2

Versão 2.2 do app com foco em performance, Docker completo e arquivos Python regenerados com validação de sintaxe.

## Como rodar

1. Extraia o pacote.
2. Copie `.env.example` para `.env`.
3. Preencha `OPENAI_API_KEY`.
4. Rode:

```bash
docker compose down --rmi all -v --remove-orphans
docker compose build --no-cache
docker compose up
```

5. Abra `http://localhost:8000`.
