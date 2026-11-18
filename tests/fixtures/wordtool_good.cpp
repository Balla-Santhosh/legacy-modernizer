#include <algorithm>
#include <cctype>
#include <iostream>
#include <string>
#include <vector>

int main(int argc, char** argv) {
    const std::vector<std::string> args(argv, argv + argc);
    if (args.size() < 3) {
        std::cerr << "usage: " << args[0] << " rev|upper|join words...\n";
        return 2;
    }
    const std::string& mode = args[1];
    if (mode == "join") {
        std::string out;
        for (std::size_t i = 2; i < args.size(); ++i) {
            out += args[i];
            if (i + 1 < args.size()) out += '-';
        }
        std::cout << out << '\n';
        return 0;
    }
    for (std::size_t i = 2; i < args.size(); ++i) {
        std::string w = args[i];
        if (mode == "rev") {
            std::reverse(w.begin(), w.end());
        } else if (mode == "upper") {
            std::transform(w.begin(), w.end(), w.begin(),
                           [](unsigned char c) { return static_cast<char>(std::toupper(c)); });
        } else {
            std::cout << std::flush;
            std::cerr << "bad mode\n";
            return 1;
        }
        std::cout << w << (i + 1 < args.size() ? " " : "\n");
    }
    return 0;
}
