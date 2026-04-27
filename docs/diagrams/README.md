# Diagramas del Proyecto AD-HOC Streaming

Todos los diagramas están en formato **PlantUML** (`.puml`) y renderizados a PNG.

## Índice

| # | Archivo | Descripción |
|---|---------|-------------|
| 1 | `01-architecture-overview.puml` | **Visión holística** — componentes software, red IBSS, particiones |
| 2 | `02-network-topology.puml` | **Topología de red** — celdas IBSS, Masters, clientes, re-fusión |
| 3 | `03-boot-sequence.puml` | **Flujo de arranque** — desde systemd hasta hilos del daemon |
| 4 | `04-streaming-sequence.puml` | **Secuencia de streaming** — relay HTTP→ffmpeg→multicast |
| 5 | `05-master-transition.puml` | **Transición de Master** — split-brain, pausa automática, reanudación |
| 6 | `06-class-diagram.puml` | **Clases Python** — NodeDaemon, AdhocManager, Streamer, Monitor |
| 7 | `07-deployment.puml` | **Despliegue físico** — USB boot, laptops, red ad-hoc sin router |
| 8 | `08-signal-power.puml` | **Presupuesto de enlace** — potencia TX, FSPL, sensibilidad RX |
| 9 | `09-packet-loss.puml` | **Estados de pérdida** — reproducción, pausa, reconexión, sniffing |

## Renderizar

```bash
# Un solo diagrama
plantuml -tpng 01-architecture-overview.puml

# Todos
for f in *.puml; do plantuml -tpng "$f"; done

# SVG (vectorial, mejor para LaTeX)
plantuml -tsvg 01-architecture-overview.puml
```

## Instalar PlantUML

```bash
# Ubuntu
sudo apt-get install plantuml

# macOS
brew install plantuml
```

## Uso en LaTeX

```latex
\begin{figure}[h]
\centering
\includegraphics[width=\textwidth]{diagrams/01-architecture-overview.png}
\caption{Visión holística de la arquitectura AD-HOC}
\end{figure}
```
