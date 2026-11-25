/* import saved csv data file into a sas dataset */
proc import 
datafile="C:\School\Stats\lotto\lottores.csv" out=work.res dbms=csv replace;
run;
proc freq data = work.res; 
   tables pb /out=work.freqpb;
run;
proc freq data = work.res; 
   tables b1/out=work.freqb1;
run;
proc freq data = work.res; 
   tables b2/out=work.freqb2;
run;
proc freq data = work.res; 
   tables b3/out=work.freqb3;
run;
proc freq data = work.res; 
   tables b4/out=work.freqb4;
run;
proc freq data = work.res; 
   tables b5/out=work.freqb5;
run;
proc export DATA = work.freqb5
outfile="C:\School\Stats\lotto\freqb5.csv" dbms=csv replace;
run;
