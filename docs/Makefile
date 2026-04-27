MAIN=main
LATEX=latexmk -pdf -interaction=nonstopmode

all:
	$(LATEX) $(MAIN).tex

clean:
	latexmk -C
	rm -f *.aux *.log *.out *.toc *.fls *.fdb_latexmk

watch:
	latexmk -pdf -pvc $(MAIN).tex
