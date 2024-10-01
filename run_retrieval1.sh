PKL=$1
HPLT_DIR=$2
OUTD=$3
mkdir -p $OUTD
find $HPLT_DIR -name "*.zst"|parallel --eta --joblog $OUTD/joblog --linebuffer -j 100 "python -u retriever.py retrieve {} --fcontent=$PKL >$OUTD/{#}.out 2>$OUTD/{#}.err"
