idf_component_register(SRCS
    "ir_ac_apply.c"
    "ir_ac_binary_parse.c"
    "ir_ac_build_frame.c"
    "ir_ac_control.c"
    "ir_ac_parse_forbidden_info.c"
    "ir_ac_parse_frame_info.c"
    "ir_ac_parse_parameter.c"
    "ir_decode.c"
    "ir_tv_control.c"
    "ir_utils.c"
    INCLUDE_DIRS "include")

target_compile_options(${COMPONENT_LIB} PRIVATE
    -Wno-format
    -Wno-unused-variable
    -Wno-unused-but-set-variable
    -Wno-sign-compare)
