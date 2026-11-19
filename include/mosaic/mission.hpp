#pragma once

#include <array>
#include <optional>
#include <string>
#include <vector>
#include <nlohmann/json.hpp>

namespace mosaic::mission {
using Json = nlohmann::json;
struct Point { double x{}, y{}; };
struct Box { double x{}, y{}, width{}, height{}; };
struct Range {
    std::string id;
    double x{}, y{}, z{}, distance{}, sigma{0.1};
};
struct Estimate {
    Point position;
    double residual{}, allowance{};
    std::vector<std::string> used, rejected;
};

bool clear_segment(Point from, Point to, const std::vector<Box>& obstacles, double clearance);
std::vector<Point> plan_path(Point from, Point to, Point minimum, Point maximum,
                             const std::vector<Box>& obstacles, double cell, double clearance,
                             std::optional<double> escape_clearance = std::nullopt);
std::optional<Estimate> locate(const std::vector<Range>& ranges, double height,
                               std::optional<Point> prior = std::nullopt);

class LocalModel {
public:
    explicit LocalModel(const Json& document);
    std::vector<double> infer(const std::vector<double>& input) const;
    std::size_t inputs() const { return inputs_; }
    const std::string& id() const { return id_; }
private:
    std::string id_;
    std::size_t inputs_{}, hidden_{}, outputs_{};
    std::vector<double> first_, first_bias_, second_, second_bias_;
};

Json execute(const Json& request, const LocalModel* model = nullptr);
} // namespace mosaic::mission
