# G16_Ordenacao_EDA2-2026.2
Projeto de Ordenação de EDA 2

# Corrida de Algoritmos

## Descrição do Projeto

Bom, o projeto foi pensado para mostrar vários algoritmos ordenação "competindo" entre si para ver qual algoritmo ordena um tipo de dado dentro de um arquivo CSV primeiro. Dentro do projeto estão todos os algoritmos de ordenação que foram estudados dentro de sala de aula, além disso ao terminar a corrida, o programa mostra uma tela de benchmarking, que busca comparar os algoritmos que foram selecionados para rodar.

## Participantes

|Aluno|Matricula|
|Bryan|231012156|
|Pablo|222014910|

## Requisitos

- Python 3.10 ou superior
- Tk instalado com a distribuição do Python

Instale as dependências:

```powershell
python -m pip install -r requirements.txt
```

## Como Rodar

```powershell
python main.py
```

Na configuração, selecione uma coluna e os algoritmos desejados. As colunas
totalmente numéricas são classificadas como inteiras ou decimais e valores
inválidos fazem a coluna ser tratada como texto, e células vazias são mantidas
e posicionadas no final da ordenação. O leitor reconhece separadores por
vírgula, ponto e vírgula ou tabulação e tenta UTF-8, Windows-1252 e Latin-1.

Counting Sort e Radix Sort são habilitados somente para colunas inteiras o Bucket
Sort é habilitado para colunas numéricas. O Counting Sort informa quando a
amplitude dos valores exigiria memória excessiva. Para arquivos grandes,
algoritmos quadráticos podem demorar bastante então a corrida pode ser pausada,
retomada ou interrompida.

O tempo exibido é tempo ativo de execução e não inclui pausas. Cada algoritmo
ordena uma cópia independente. A ordenação é crescente e valores ausentes ficam
no final. A exportação contém somente algoritmos que concluíram com sucesso.