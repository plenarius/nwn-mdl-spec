// SPDX-License-Identifier: CC0-1.0
// nwn-mdl-spec adapter for Moonglow Toolset's mg-mdl crate.
//   mgconf compile   <in.mdl> <out.mdl>   mg_mdl::compile::compile_named; a
//                                         supermodel is looked up next to the input
//   mgconf decompile <in.mdl> <out.mdl>   mg_mdl::decompile
// Compiler notes go to stderr; exit 1 on an error.
use std::{env, fs, path::Path, process::ExitCode};

fn main() -> ExitCode {
    let a: Vec<String> = env::args().collect();
    if a.len() != 4 {
        eprintln!("usage: mgconf compile|decompile <in> <out>");
        return ExitCode::from(2);
    }
    let input = Path::new(&a[2]);
    let data = match fs::read(input) {
        Ok(d) => d,
        Err(e) => {
            eprintln!("read {}: {e}", a[2]);
            return ExitCode::from(1);
        }
    };
    match a[1].as_str() {
        "decompile" => match mg_mdl::decompile(&data) {
            Ok(text) => fs::write(&a[3], text).expect("write"),
            Err(e) => {
                eprintln!("decompile error: {e}");
                return ExitCode::from(1);
            }
        },
        "compile" => {
            let dir = input.parent().map(Path::to_path_buf).unwrap_or_default();
            let name = input.file_stem().and_then(|s| s.to_str()).unwrap_or("").to_string();
            let lookup = |n: &str| fs::read(dir.join(format!("{n}.mdl"))).ok();
            let none = |_: &str| None;
            match mg_mdl::compile::compile_named(&data, &name, &lookup, &none) {
                Ok(c) => {
                    for (line, note) in &c.notes {
                        eprintln!("note line {line}: {note}");
                    }
                    fs::write(&a[3], c.binary).expect("write");
                }
                Err(e) => {
                    eprintln!("compile error: {e}");
                    return ExitCode::from(1);
                }
            }
        }
        _ => return ExitCode::from(2),
    }
    ExitCode::SUCCESS
}
