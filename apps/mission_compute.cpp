#include "mosaic/mission.hpp"
#include <fstream>
#include <iostream>
#include <memory>
#include <string>

int main(int argc, char** argv) {
    using namespace mosaic::mission;
    try {
        std::unique_ptr<LocalModel> model;
        if (argc==3 && std::string(argv[1])=="--model") {
            std::ifstream input(argv[2]);if (!input) throw std::runtime_error("cannot_open_model");
            Json document;input>>document;model=std::make_unique<LocalModel>(document);
        } else if (argc!=1) throw std::invalid_argument("usage: mosaic-mission-compute [--model FILE]");
        std::string line;
        while (std::getline(std::cin,line)) {
            Json response;
            try {
                if (line.size()>1024*1024) throw std::invalid_argument("request_capacity");
                response=execute(Json::parse(line),model.get());response["ok"]=true;
            } catch (const std::exception& error) {response={{"ok",false},{"error",error.what()}};}
            std::cout<<response.dump()<<'\n'<<std::flush;
        }
    } catch (const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
