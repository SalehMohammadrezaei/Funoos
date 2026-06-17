CXX ?= g++
CXXFLAGS ?= -O3 -march=native -fopenmp -std=c++17 -Wall

lbm2d: lbm2d.cpp
	$(CXX) $(CXXFLAGS) -o lbm2d lbm2d.cpp

clean:
	rm -f lbm2d
